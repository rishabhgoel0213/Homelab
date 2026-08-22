# Local Models in Pi

Pi receives local OpenAI-compatible models from the declarative
`homelab.pi.localModels` registry. Every entry appears under the single
`homelab-local` provider. Runtime services remain model-specific so llama.cpp,
vLLM, Ollama, and custom engines can share the Pi integration without sharing
incorrect lifecycle assumptions.

## Mach-1 Additive 35B

The Mach-1 service uses its native packed checkpoint and WebGPU kernels through
NVIDIA Vulkan. The checkpoint lives outside Git under
`/srv/state/local-models/mach1-additive-35b`.

On the first deployment, materialize and verify the pinned checkpoint, then
start the service:

```bash
just local-model-fetch mach1-additive-35b
sudo systemctl start docker-mach1-additive-35b.service
just local-model-doctor mach1-additive-35b
```

Launch Pi with the local model:

```bash
pi --model homelab-local/mach1-additive-35b
```

Mach-1 is advertised with a 65,536-token context and a 4,096-token output
limit. Enable its model-emitted reasoning trace with Pi's thinking control:

```bash
pi --model homelab-local/mach1-additive-35b --thinking high
```

All non-off thinking levels enable Mach-1's native thinking mode; the model
does not distinguish effort levels internally. Pi renders the trace as a
separate thinking block rather than literal `<think>` tags. `--thinking off`
retains answer-only generation.

Prompt prefill is submitted in exact eight-token batches and the runtime keeps
one exact GPU snapshot of the leading system/tool prefix. This does not alter
model arithmetic or sampling. The first request warms the prefix cache;
subsequent requests with the same Pi system prompt and tool set skip those
cached prompt tokens. Non-streaming API responses expose `prefill_ms`,
`prefill_batch_size`, `prefix_cache_hit`, and `cached_prompt_tokens` under
`timings`. For controlled comparisons only, send `prefill_batch_size: 1` or
`prefix_cache: false` in the OpenAI-compatible request body.

The service binds only to `127.0.0.1:8000`. It uses Docker host networking
because the host's Tailscale exit-node routing captures Docker bridge traffic.

## Ternary Bonsai 27B

Bonsai uses Prism ML's pinned CUDA llama.cpp fork and the publisher's native
Q2_0_g128 GGUF. The 7.165 GB checkpoint is stored outside Git under
`/srv/state/local-models/bonsai-ternary-27b`. Download and activate it with:

```bash
just local-model-fetch bonsai-ternary-27b
just local-model-use bonsai-ternary-27b
just local-model-doctor bonsai-ternary-27b
```

Then launch Pi with:

```bash
pi --model homelab-local/bonsai-ternary-27b
```

The service advertises a 100,000-token context and an 8,192-token output
limit. It uses the model publisher's recommended 4-bit GPU KV cache to keep
that context inside 12 GB VRAM. This is a small context-state precision
tradeoff, not an additional weight quantization; the shipped model's published
quality and long-context measurements use the same 4-bit KV operating point.

Mach-1 and Bonsai cannot reside together on this 12 GB GPU. Starting either
model automatically stops the other through a systemd conflict. Use
`just local-model-use <model-id>` to switch; the default boot model remains
Mach-1. Bonsai's llama.cpp slot cache automatically reuses a matching Pi
system/tool prefix across launches while the service remains running.

A loopback-only compatibility proxy maps Pi's reasoning level to Bonsai's
native `enable_thinking` chat-template argument. `--thinking off` produces a
direct answer; any non-off Pi thinking level enables the model's reasoning and
streams it through `reasoning_content`.

The Bonsai API binds only to `127.0.0.1:8001`. Non-streaming responses include
llama.cpp's `timings` object, which reports prompt-evaluation and generation
throughput directly.

## Adding another model

Implement the runtime in its own service module, normalize its endpoint to an
API Pi supports, and add one registry entry:

```nix
homelab.pi.localModels.example = {
  displayName = "Example Local Model";
  baseUrl = "http://127.0.0.1:8080/v1";
  contextWindow = 32768;
  maxTokens = 4096;
  serviceUnit = "example-model.service";
  healthUrl = "http://127.0.0.1:8080/health";
};
```

Use a different model ID and endpoint, but keep the provider name
`homelab-local`. `local-model-doctor` checks the declared unit and health URL.
If the runtime needs checkpoint acquisition, expose a bounded oneshot unit and
set `fetchUnit` so `just local-model-fetch <id>` can invoke it.
