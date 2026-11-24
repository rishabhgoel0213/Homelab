# Local Models

## Qwen-Image 2.1

Qwen-Image uses ComfyUI's native Qwen-Image 2.1 implementation with the
official ComfyUI INT8 ConvRot diffusion model and text encoder plus the BF16
VAE. This is the quality-oriented configuration that fits the host's 12 GB
RTX 3060 without the full 33.1 GB BF16 checkpoint. The pinned files occupy
about 17.3 GB under `/srv/state/local-models/qwen-image-2.1`.

The model is available only under the Qwen Research License Agreement for
non-commercial research and evaluation. Downloading or using it constitutes
acceptance of that license. The fetch unit stores the exact license beside the
weights.

Fetch and activate the model:

```bash
just qwen-image-fetch
just qwen-image-use
```

Edit an image directly:

```bash
qwen-image-edit photo.png "replace the sky with a dramatic sunset"
```

Add up to 15 reference images with repeatable `--reference`/`-r` options. The
primary positional image is Image 1 and controls the output dimensions; the
references are Image 2 onward:

```bash
qwen-image-edit portrait.jpg \
  -r clothing.jpg \
  -r background.jpg \
  "put the person from Image 1 in the clothing from Image 2 and setting from Image 3"
```

Run `qwen-image-edit` without arguments to pick one or more images beneath the
current directory with `fzf` (`Tab` toggles each selection), then enter the edit
description interactively. The default is the official ComfyUI 25-step workflow
at a roughly one-megapixel pixel budget; use `--resolution 0` to retain the
input dimensions or `--steps 40` for the slower official Diffusers sampling
depth. Output is saved beside the input unless `--output` is provided.

The loopback-only service remains loaded after a request so consecutive edits
avoid cold-start costs. Stop it explicitly with `just qwen-image-stop`.
