import { createServer, request as requestBackend } from "node:http";

const listenHost = process.env.BONSAI_HOST ?? "127.0.0.1";
const listenPort = Number(process.env.BONSAI_PORT ?? 8001);
const backendHost = "127.0.0.1";
const backendPort = Number(process.env.BONSAI_BACKEND_PORT ?? 8002);
const maxBodyBytes = 32 * 1024 * 1024;

function thinkingEnabled(body) {
  const effort = body.reasoning_effort ?? body.reasoning?.effort;
  return effort != null && !["none", "off"].includes(String(effort).toLowerCase());
}

async function requestBody(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maxBodyBytes) throw new Error("request body exceeds 32 MiB");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function proxy(request, response, body = null) {
  const headers = { ...request.headers, host: `${backendHost}:${backendPort}` };
  if (body) headers["content-length"] = String(body.length);
  const upstream = requestBackend({
    host: backendHost,
    port: backendPort,
    method: request.method,
    path: request.url,
    headers,
  }, (backendResponse) => {
    response.writeHead(backendResponse.statusCode ?? 502, backendResponse.headers);
    backendResponse.pipe(response);
  });
  upstream.on("error", (error) => {
    if (response.headersSent || response.destroyed) return response.destroy(error);
    const payload = JSON.stringify({ error: { message: error.message, type: "backend_unavailable" } });
    response.writeHead(502, {
      "content-type": "application/json",
      "content-length": Buffer.byteLength(payload),
    });
    response.end(payload);
  });
  request.once("aborted", () => upstream.destroy());
  response.once("close", () => {
    if (!response.writableEnded) upstream.destroy();
  });
  if (body) upstream.end(body);
  else request.pipe(upstream);
}

const server = createServer(async (request, response) => {
  try {
    if (request.method === "POST" && request.url?.startsWith("/v1/chat/completions")) {
      const raw = await requestBody(request);
      const body = JSON.parse(raw.toString("utf8"));
      body.chat_template_kwargs = {
        ...(body.chat_template_kwargs ?? {}),
        enable_thinking: thinkingEnabled(body),
      };
      return proxy(request, response, Buffer.from(JSON.stringify(body)));
    }
    return proxy(request, response);
  } catch (error) {
    const payload = JSON.stringify({ error: { message: error.message, type: "invalid_request_error" } });
    response.writeHead(400, {
      "content-type": "application/json",
      "content-length": Buffer.byteLength(payload),
    });
    response.end(payload);
  }
});

server.listen(listenPort, listenHost, () => {
  console.log(`[proxy] listening on http://${listenHost}:${listenPort}, backend ${backendHost}:${backendPort}`);
});
