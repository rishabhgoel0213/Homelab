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
