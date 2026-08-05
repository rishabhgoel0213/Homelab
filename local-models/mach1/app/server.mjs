import { createReadStream } from "node:fs";
import { access, mkdir, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import process from "node:process";
import { parseToolOutput } from "./web/tool-calls.mjs";

const projectRoot = process.env.MACH1_APP_ROOT
  ? path.resolve(process.env.MACH1_APP_ROOT)
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const webRoot = path.join(projectRoot, "app", "web");
const vendorRoot = path.join(projectRoot, "vendor", "mach1");
const modelRoot = path.resolve(process.env.MODEL_DIR ?? path.join(process.cwd(), "models"));
const host = process.env.MACH1_HOST ?? "0.0.0.0";
const port = Number(process.env.MACH1_PORT ?? 8000);
const maxContext = Number(process.env.MACH1_MAX_CONTEXT ?? 16384);
const maxCompletionTokens = Number(process.env.MACH1_MAX_TOKENS ?? 4096);

const state = {
  status: "starting",
  stage: "http server",
  fraction: 0,
  model: "mach-1-additive-35b",
  model_dir: modelRoot,
  max_context_tokens: maxContext,
  max_completion_tokens: maxCompletionTokens,
  error: null,
};
let browser = null;
let xvfb = null;
let page = null;
let queue = Promise.resolve();
const streams = new Map();

function json(response, statusCode, value) {
  const body = JSON.stringify(value);
  response.writeHead(statusCode, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
  });
  response.end(body);
}

function safePath(root, requestPath) {
  const decoded = decodeURIComponent(requestPath);
  const resolved = path.resolve(root, `.${decoded}`);
  if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) return null;
  return resolved;
}

async function serveFile(request, response, root, requestPath) {
  const filename = safePath(root, requestPath);
  if (!filename) return json(response, 400, { error: "invalid path" });
  let metadata;
  try {
    metadata = await stat(filename);
  } catch {
    return json(response, 404, { error: "not found" });
  }
  if (!metadata.isFile()) return json(response, 404, { error: "not found" });

  const extension = path.extname(filename);
  const contentType = extension === ".js" || extension === ".mjs" ? "text/javascript; charset=utf-8"
    : extension === ".html" ? "text/html; charset=utf-8"
    : extension === ".json" ? "application/json"
    : "application/octet-stream";
  let start = 0;
  let end = metadata.size - 1;
  let statusCode = 200;
  const range = request.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
  if (range) {
    start = Number(range[1]);
    end = range[2] ? Math.min(Number(range[2]), end) : end;
    if (start > end) {
      response.writeHead(416, { "content-range": `bytes */${metadata.size}` });
      return response.end();
    }
    statusCode = 206;
  }
  const headers = {
    "accept-ranges": "bytes",
    "cache-control": root === modelRoot ? "public, max-age=31536000, immutable" : "no-cache",
    "content-length": end - start + 1,
    "content-type": contentType,
  };
  if (statusCode === 206) headers["content-range"] = `bytes ${start}-${end}/${metadata.size}`;
  response.writeHead(statusCode, headers);
  if (request.method === "HEAD") return response.end();
  createReadStream(filename, { start, end }).pipe(response);
}

async function readJson(request) {
  let size = 0;
  const chunks = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 1024 * 1024) throw new Error("request body exceeds 1 MiB");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function completionId() {
  return `chatcmpl-mach1-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function enqueue(task) {
  const result = queue.then(task);
  queue = result.catch(() => {});
  return result;
}

function cancelEvaluation(requestId) {
  if (!page) return;
  void page.evaluate(
    (id) => globalThis.__mach1?.cancel?.(id),
    requestId,
  ).catch((error) => console.warn(`[cancel] ${String(error.message ?? error)}`));
}

async function handleCompletion(request, response) {
  if (state.status !== "ready" || !page) {
    return json(response, 503, { error: { message: `model is ${state.status}: ${state.stage}`, type: "service_unavailable" } });
  }
  let body;
  try {
    body = await readJson(request);
  } catch (error) {
    return json(response, 400, { error: { message: String(error.message ?? error), type: "invalid_request_error" } });
  }
  const id = completionId();
  const created = Math.floor(Date.now() / 1000);
  const stream = body.stream === true;
  let cancelled = false;
  let completed = false;
  const cancel = () => {
    if (cancelled || completed) return;
    cancelled = true;
    streams.delete(id);
    cancelEvaluation(id);
  };
  const handleResponseClose = () => {
    if (!response.writableEnded) cancel();
  };
  request.once("aborted", cancel);
  response.once("close", handleResponseClose);
  if (stream) {
    response.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
    });
    streams.set(id, { response, created });
  }

  try {
    const hasTools = Array.isArray(body.tools) && body.tools.length > 0;
    const result = await enqueue(() => page.evaluate(
      async ({ requestBody, requestId, streamContent, streamReasoning }) => globalThis.__mach1.complete(
        requestBody,
        requestId,
        streamContent,
        streamReasoning,
      ),
      {
        requestBody: body,
        requestId: id,
        streamContent: stream && !hasTools,
        streamReasoning: stream,
      },
    ));
    completed = true;
    const usage = {
      prompt_tokens: result.promptTokens,
      completion_tokens: result.completionTokens,
      total_tokens: result.promptTokens + result.completionTokens,
    };
    const allowedToolNames = hasTools
      ? body.tools.flatMap((tool) => typeof tool?.function?.name === "string" ? [tool.function.name] : [])
      : [];
    const parsed = hasTools
      ? parseToolOutput(result.text, undefined, allowedToolNames)
      : { content: result.text, toolCalls: [], errors: [] };
    if (parsed.errors.length) console.warn(`[tool] left malformed tool output as text: ${parsed.errors.join("; ")}`);
    const finishReason = parsed.toolCalls.length ? "tool_calls" : result.hitLimit ? "length" : "stop";
    if (stream) {
      if (hasTools && parsed.content) {
        response.write(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", created, model: state.model, choices: [{ index: 0, delta: { content: parsed.content }, finish_reason: null }] })}\n\n`);
      }
      if (hasTools) {
        for (const [index, toolCall] of parsed.toolCalls.entries()) {
          response.write(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", created, model: state.model, choices: [{ index: 0, delta: { tool_calls: [{ index, ...toolCall }] }, finish_reason: null }] })}\n\n`);
        }
      }
      response.write(`data: ${JSON.stringify({ id, object: "chat.completion.chunk", created, model: state.model, choices: [{ index: 0, delta: {}, finish_reason: finishReason }], usage })}\n\n`);
      response.write("data: [DONE]\n\n");
      response.end();
      streams.delete(id);
      return;
    }
    return json(response, 200, {
      id,
      object: "chat.completion",
      created,
      model: state.model,
      choices: [{
        index: 0,
        message: {
          role: "assistant",
          content: parsed.content,
          ...(result.reasoningText != null ? { reasoning_content: result.reasoningText } : {}),
          ...(parsed.toolCalls.length ? { tool_calls: parsed.toolCalls } : {}),
        },
        finish_reason: finishReason,
      }],
      usage,
      timings: {
        elapsed_ms: Math.round(result.elapsedMs),
        prefill_ms: Math.round(result.prefillMs),
        generation_ms: Math.round(result.generationMs),
        prefill_batch_size: result.prefillBatchSize,
        prefix_cache_hit: result.prefixCacheHit,
        cached_prompt_tokens: result.cachedPromptTokens,
      },
    });
  } catch (error) {
    completed = true;
    streams.delete(id);
    if (cancelled || response.destroyed) return;
    if (stream) {
      response.write(`data: ${JSON.stringify({ error: { message: String(error.message ?? error), type: "server_error" } })}\n\n`);
      response.write("data: [DONE]\n\n");
      return response.end();
    }
    return json(response, 500, { error: { message: String(error.message ?? error), type: "server_error" } });
  } finally {
    request.off("aborted", cancel);
    response.off("close", handleResponseClose);
  }
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${request.headers.host ?? "localhost"}`);
    if (url.pathname === "/health") {
      const statusCode = state.status === "ready" ? 200 : state.status === "error" ? 500 : 503;
      return json(response, statusCode, state);
    }
    if (url.pathname === "/v1/models") {
      return json(response, 200, { object: "list", data: [{ id: state.model, object: "model", owned_by: "SyzygyResearch" }] });
    }
    if (url.pathname === "/v1/chat/completions" && request.method === "POST") {
      return await handleCompletion(request, response);
    }
    if (url.pathname === "/" || url.pathname === "/internal/engine") {
      return await serveFile(request, response, webRoot, "/index.html");
    }
    if (url.pathname.startsWith("/app/")) {
      return await serveFile(request, response, webRoot, url.pathname.slice(4));
    }
    if (url.pathname.startsWith("/vendor/")) {
      return await serveFile(request, response, vendorRoot, url.pathname.slice(7));
    }
    if (url.pathname.startsWith("/model/")) {
      return await serveFile(request, response, modelRoot, url.pathname.slice(6));
    }
    return json(response, 404, { error: "not found" });
  } catch (error) {
    return json(response, 500, { error: String(error.stack ?? error) });
  }
});

async function chooseDisplay() {
  for (let number = 90; number < 120; number++) {
    try {
      await access(`/tmp/.X11-unix/X${number}`);
    } catch {
      return { number, display: `:${number}` };
    }
  }
  throw new Error("no free X display between :90 and :119");
}

async function startBrowser() {
  const playwrightPath = process.env.PLAYWRIGHT_CORE;
  const chromiumPath = process.env.CHROMIUM_BIN;
  const xvfbPath = process.env.XVFB_BIN;
  if (!playwrightPath || !chromiumPath || !xvfbPath) {
    throw new Error("PLAYWRIGHT_CORE, CHROMIUM_BIN, and XVFB_BIN must be set by the Nix wrapper");
  }
  await stat(modelRoot);
  const { number, display } = await chooseDisplay();
  const runtimeDir = `/tmp/mach1-runtime-${process.pid}`;
  await mkdir(runtimeDir, { recursive: true, mode: 0o700 });
  process.env.XDG_RUNTIME_DIR = runtimeDir;
  process.env.DISPLAY = display;
  const xkbRoot = process.env.XKB_CONFIG_ROOT;
  const xvfbArgs = [display, "-screen", "0", "1280x720x24", "-nolisten", "tcp"];
  if (xkbRoot) xvfbArgs.push("-xkbdir", xkbRoot);
  xvfb = spawn(xvfbPath, xvfbArgs, {
    stdio: ["ignore", "ignore", "inherit"],
  });
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      await access(`/tmp/.X11-unix/X${number}`);
      break;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
  await access(`/tmp/.X11-unix/X${number}`);

  const { chromium } = await import(`${playwrightPath}/index.mjs`);
  browser = await chromium.launch({
    executablePath: chromiumPath,
    headless: false,
    args: [
      "--no-sandbox",
      "--disable-gpu-sandbox",
      "--enable-unsafe-webgpu",
      "--ignore-gpu-blocklist",
      "--use-gl=angle",
      "--use-angle=vulkan",
      "--enable-features=Vulkan,VulkanFromANGLE,DefaultANGLEVulkan",
      "--ozone-platform=x11",
      "--disable-vulkan-surface",
    ],
  });
  page = await browser.newPage();
  page.on("console", (message) => console.log(`[browser:${message.type()}] ${message.text()}`));
  page.on("pageerror", (error) => console.error(`[browser:error] ${error.stack ?? error}`));
  await page.exposeFunction("__mach1Progress", (progress) => {
    Object.assign(state, progress);
    if (progress.stage) console.log(`[model] ${progress.stage} ${Math.round((progress.fraction ?? 0) * 100)}%`);
  });
  await page.exposeFunction("__mach1Token", ({ requestId, channel, piece }) => {
    const target = streams.get(requestId);
    if (!target || target.response.destroyed) return;
    target.response.write(`data: ${JSON.stringify({
      id: requestId,
      object: "chat.completion.chunk",
      created: target.created,
      model: state.model,
      choices: [{
        index: 0,
        delta: channel === "reasoning" ? { reasoning_content: piece } : { content: piece },
        finish_reason: null,
      }],
    })}\n\n`);
  });
  state.status = "loading";
  state.stage = "opening inference worker";
  await page.goto(
    `http://127.0.0.1:${port}/internal/engine?max_ctx=${maxContext}&max_tokens=${maxCompletionTokens}`,
    { waitUntil: "load" },
  );
  await page.waitForFunction(() => globalThis.__mach1?.ready || globalThis.__mach1State?.status === "error", null, { timeout: 0 });
  const browserState = await page.evaluate(() => ({ runtime: globalThis.__mach1State, engine: globalThis.__mach1 }));
  if (!browserState.engine?.ready) throw new Error(browserState.runtime?.error ?? "WebGPU engine failed to initialize");
  state.status = "ready";
  state.stage = "ready";
  state.fraction = 1;
  state.gpu = browserState.engine.gpu;
  state.max_context_tokens = browserState.engine.maxCtx;
  console.log(`[ready] ${state.model} on port ${port}`);
}

async function shutdown(signal) {
  console.log(`[shutdown] ${signal}`);
  server.close();
  for (const { response } of streams.values()) response.end();
  streams.clear();
  try { await browser?.close(); } catch {}
  if (xvfb && !xvfb.killed) xvfb.kill("SIGTERM");
  process.exit(0);
}

for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => void shutdown(signal));

server.listen(port, host, () => {
  console.log(`[http] listening on ${host}:${port}`);
  void startBrowser().catch((error) => {
    state.status = "error";
    state.stage = "startup failed";
    state.error = String(error.stack ?? error);
    console.error(state.error);
  });
});
