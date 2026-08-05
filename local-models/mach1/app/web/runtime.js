import { initGPU } from "/vendor/gpu.js";
import { Engine } from "/vendor/engine.js";
import { createReasoningStream, splitReasoningOutput } from "/app/reasoning.mjs";
import { renderAssistantToolCalls } from "/app/tool-calls.mjs";

const statusElement = document.querySelector("#status");
const runtimeState = { status: "initializing", stage: "webgpu", fraction: 0, error: null };
const cancelledRequests = new Set();
globalThis.__mach1State = runtimeState;

function report(stage, fraction = runtimeState.fraction) {
  runtimeState.stage = stage;
  runtimeState.fraction = fraction;
  statusElement.textContent = JSON.stringify(runtimeState, null, 2);
  globalThis.__mach1Progress?.({ ...runtimeState });
}

function textContent(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return content == null ? "" : String(content);
  return content.filter((part) => part?.type === "text" || "text" in (part ?? {}))
    .map((part) => part.text ?? "").join("");
}

function renderMessages(messages, tools) {
  const turns = [];
  if (Array.isArray(tools) && tools.length) {
    turns.push({
      role: "system",
      content: `# Tools\n\nYou have access to the following functions:\n\n<tools>\n${tools.map((tool) => JSON.stringify(tool)).join("\n")}\n</tools>\n\nTo call a function, output only this exact format:\n<tool>\n{"name":"function_name","arguments":{"argument_name":"value"}}\n</tool>\nDo not describe the call or use a bare function name followed by key=value arguments.`,
    });
  }
  for (const message of messages ?? []) {
    if (!["system", "user", "assistant", "tool"].includes(message?.role)) continue;
    let content = textContent(message.content);
    if (message.role === "assistant" && Array.isArray(message.tool_calls)) {
      const rendered = renderAssistantToolCalls(message.tool_calls);
      content = [content, rendered].filter(Boolean).join("\n");
    }
    if (message.role === "tool") content = `<tool_response>\n${content}\n</tool_response>`;
    turns.push({ role: message.role === "tool" ? "user" : message.role, content });
  }
  return turns;
}

function requestedThinking(body) {
  const value = body.reasoning_effort ?? body.reasoning?.effort;
  return value != null && !["none", "off"].includes(String(value).toLowerCase());
}

function encodePrompt(engine, body, requestedTokens, thinking) {
  const turn = (role, content) => `<|im_start|>${role}\n${content}<|im_end|>\n`;
  const turns = renderMessages(body.messages, body.tools);
  if (!turns.length) throw new Error("messages must contain at least one supported message");

  for (let drop = 0; drop <= turns.length; drop++) {
    const kept = turns.filter((message, index) => message.role === "system" || index >= drop);
    let prompt = kept.map((message) => turn(message.role, message.content)).join("");
    prompt += thinking
      ? "<|im_start|>assistant\n<think>\n"
      : "<|im_start|>assistant\n<think>\n\n</think>\n\n";
    const ids = engine.tok.encode(prompt);
    if (ids.length + requestedTokens + 1 < engine.maxCtx) {
      const leadingSystem = [];
      for (const message of kept) {
        if (message.role !== "system") break;
        leadingSystem.push(message);
      }
      const prefixIds = engine.tok.encode(
        leadingSystem.map((message) => turn(message.role, message.content)).join(""),
      );
      const isExactPrefix = prefixIds.every((id, index) => ids[index] === id);
      return { ids, prefixLength: isExactPrefix ? prefixIds.length : 0 };
    }
  }
  throw new Error(`prompt is too large for the configured ${engine.maxCtx}-token context`);
}

try {
  report("requesting GPU", 0);
  const { device, info } = await initGPU();
  runtimeState.gpu = info;
  report("loading packed model", 0.01);
  const query = new URLSearchParams(location.search);
  const maxCtx = Number(query.get("max_ctx") || 2048);
  const maxCompletionTokens = Number(query.get("max_tokens") || 4096);
  const engine = await Engine.load(device, "/model", {
    model: "additive",
    addOnly: true,
    maxCtx,
    onProgress: (stage, fraction) => report(stage, fraction),
  });
  engine.ADD_ONLY = true;

  globalThis.__mach1 = {
    ready: true,
    model: "mach-1-additive-35b",
    maxCtx,
    maxCompletionTokens,
    gpu: info,
    cancel(requestId) {
      if (!requestId) return;
      cancelledRequests.add(requestId);
      setTimeout(() => cancelledRequests.delete(requestId), 300000);
    },
    async complete(body, requestId = null, streamContent = false, streamReasoning = false) {
      const requested = Math.max(1, Math.min(maxCompletionTokens,
        Number(body.max_completion_tokens ?? body.max_tokens ?? 128)));
      const thinking = requestedThinking(body);
      const prompt = encodePrompt(engine, body, requested, thinking);
      const promptIds = prompt.ids;
      const maxTokens = Math.max(1, Math.min(requested, engine.maxCtx - promptIds.length - 1));
      const temperature = Number(body.temperature ?? 0.7);
      const topP = Number(body.top_p ?? 0.9);
      const started = performance.now();
      const ensureActive = () => {
        if (requestId && cancelledRequests.has(requestId)) {
          throw new DOMException("client cancelled generation", "AbortError");
        }
      };
      try {
        ensureActive();
        const reasoningStream = createReasoningStream(thinking, ({ channel, piece }) => {
          if (!requestId) return;
          if ((channel === "reasoning" && streamReasoning)
            || (channel === "content" && streamContent)) {
            void globalThis.__mach1Token?.({ requestId, channel, piece });
          }
        });
        const generated = await engine.generate(promptIds, {
          maxTokens,
          temperature,
          topP,
          onPrefill: ensureActive,
          shouldStop: () => requestId ? cancelledRequests.has(requestId) : false,
          prefixLength: prompt.prefixLength,
          usePrefixCache: body.prefix_cache !== false,
          prefillBatchSize: Number(body.prefill_batch_size ?? engine.prefillBatchSize),
          onToken: (piece) => {
            ensureActive();
            reasoningStream.push(piece);
          },
        });
        reasoningStream.finish();
        const output = splitReasoningOutput(generated.text, thinking);
        return {
          text: output.content,
          reasoningText: output.reasoning,
          promptTokens: promptIds.length,
          completionTokens: generated.ids.length,
          hitLimit: generated.ids.length >= maxTokens,
          elapsedMs: performance.now() - started,
          prefillMs: generated.prefillMs,
          generationMs: performance.now() - started - generated.prefillMs,
          prefillBatchSize: generated.prefillBatchSize,
          prefixCacheHit: generated.prefixCacheHit,
          cachedPromptTokens: generated.cachedPromptTokens,
        };
      } finally {
        if (requestId) cancelledRequests.delete(requestId);
      }
    },
  };
  runtimeState.status = "ready";
  report("ready", 1);
} catch (error) {
  runtimeState.status = "error";
  runtimeState.error = String(error?.stack ?? error);
  report("failed", runtimeState.fraction);
  console.error(error);
}
