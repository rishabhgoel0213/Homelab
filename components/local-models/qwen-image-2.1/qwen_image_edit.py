#!/usr/bin/env python3
"""Submit a Qwen-Image 2.1 edit to the local ComfyUI service."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


SERVICE = "qwen-image-2.1.service"
BASE_URL = os.environ.get("QWEN_IMAGE_URL", "http://127.0.0.1:8188")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MAX_IMAGES = 16


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select one or more images and edit them with local Qwen-Image 2.1.",
        epilog=(
            'example: qwen-image-edit photo.png -r style.jpg '
            '"edit Image 1 using the style of Image 2"'
        ),
    )
    parser.add_argument(
        "image", nargs="?", type=Path,
        help="primary image; omit to select one or more images with fzf",
    )
    parser.add_argument("instruction", nargs="*", help="edit description; omit for an interactive prompt")
    parser.add_argument(
        "-r", "--reference", action="append", default=[], type=Path, metavar="IMAGE",
        help="additional reference image; repeat for up to 15 references",
    )
    parser.add_argument("-o", "--output", type=Path, help="output PNG path")
    parser.add_argument("--steps", type=int, default=25, help="sampling steps (default: 25)")
    parser.add_argument(
        "--resolution", type=int, default=1024,
        help="pixel-budget side length; 0 preserves input dimensions (default: 1024)",
    )
    parser.add_argument("--seed", type=int, help="deterministic seed; random by default")
    parser.add_argument("--negative-prompt", default="", help="negative prompt (normally unused at CFG 1)")
    parser.add_argument("--no-start", action="store_true", help="do not start the system service automatically")
    args = parser.parse_args()
    if not 1 <= args.steps <= 100:
        parser.error("--steps must be between 1 and 100")
    if args.resolution != 0 and not 256 <= args.resolution <= 2048:
        parser.error("--resolution must be 0 or between 256 and 2048")
    return args


def select_images() -> list[Path]:
    if not sys.stdin.isatty():
        raise SystemExit("an input image is required when stdin is not interactive")
    if shutil.which("fzf") is None:
        raise SystemExit("fzf is unavailable; pass an image path explicitly")
    choices = sorted(
        str(path) for path in Path.cwd().rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not choices:
        raise SystemExit(f"no supported images found beneath {Path.cwd()}")
    selected = subprocess.run(
        [
            "fzf", "--multi", f"--bind=tab:toggle+down",
            "--prompt=Images (TAB selects)> ", "--height=60%", "--reverse",
        ],
        input="\n".join(choices) + "\n", text=True, stdout=subprocess.PIPE, check=False,
    )
    if selected.returncode != 0 or not selected.stdout.strip():
        raise SystemExit("image selection cancelled")
    return [Path(line) for line in selected.stdout.splitlines() if line]


def ensure_service(no_start: bool) -> None:
    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE], check=False
    ).returncode == 0
    if not active:
        if no_start:
            raise SystemExit(f"{SERVICE} is not running")
        print(f"Starting {SERVICE}; this may request sudo authentication...", file=sys.stderr)
        subprocess.run(["sudo", "systemctl", "start", SERVICE], check=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/system_stats", timeout=2):
                return
        except (OSError, urllib.error.URLError):
            time.sleep(1)
    raise SystemExit(f"timed out waiting for {SERVICE}")


def request_json(path: str, payload: object | None = None) -> dict:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"ComfyUI returned HTTP {error.code}: {detail}") from error


def upload_image(path: Path) -> str:
    boundary = f"----qwen-image-{uuid.uuid4().hex}"
    remote_name = f"qwen-image-cli-{uuid.uuid4().hex}{path.suffix.lower()}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\ninput\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
         f"filename=\"{remote_name}\"\r\nContent-Type: {content_type}\r\n\r\n").encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        f"{BASE_URL}/upload/image", data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            uploaded = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"image upload failed with HTTP {error.code}: {detail}") from error
    return f"{uploaded.get('subfolder', '')}/{uploaded['name']}".lstrip("/")


def workflow(
    image_names: list[str], prompt: str, negative: str, steps: int, resolution: int, seed: int,
) -> dict:
    if not 1 <= len(image_names) <= MAX_IMAGES:
        raise ValueError(f"workflow requires between 1 and {MAX_IMAGES} images")

    text_inputs: dict[str, object] = {
        "clip": ["2", 0], "prompt": prompt, "negative_prompt": negative,
        "vae": ["3", 0], "resolution": resolution,
    }
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {
            "vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "5": {"class_type": "TextEncodeQwenImage21", "inputs": text_inputs},
        "6": {"class_type": "QwenImage21Cache", "inputs": {
            "model": ["1", 0], "device": "cpu", "dtype": "default"}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["6", 0], "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "positive": ["5", 0],
            "negative": ["5", 1], "latent_image": ["5", 2], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0], "filename_prefix": f"qwen-image-cli/{uuid.uuid4().hex}"}},
    }
    for index, image_name in enumerate(image_names, start=1):
        node_id = "4" if index == 1 else str(index + 8)
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
        text_inputs[f"images.image_{index}"] = [node_id, 0]
    return graph


def await_output(prompt_id: str) -> dict:
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        history = request_json(f"/history/{urllib.parse.quote(prompt_id)}")
        if prompt_id in history:
            record = history[prompt_id]
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise SystemExit(f"generation failed: {json.dumps(status.get('messages', []), indent=2)}")
            images = record.get("outputs", {}).get("9", {}).get("images", [])
            if images:
                return images[0]
        time.sleep(1)
    raise SystemExit("timed out waiting for image generation")


def download_output(info: dict, destination: Path) -> None:
    query = urllib.parse.urlencode({
        "filename": info["filename"], "subfolder": info.get("subfolder", ""),
        "type": info.get("type", "output"),
    })
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    with urllib.request.urlopen(f"{BASE_URL}/view?{query}", timeout=120) as response:
        temporary.write_bytes(response.read())
    temporary.replace(destination)


def main() -> int:
    args = parse_args()
    selected = [args.image, *args.reference] if args.image else select_images()
    sources = [source.expanduser().resolve() for source in selected]
    if len(sources) > MAX_IMAGES:
        raise SystemExit(f"at most {MAX_IMAGES} input images are supported")
    for source in sources:
        if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
            raise SystemExit(f"unsupported or missing input image: {source}")
    instruction = " ".join(args.instruction).strip()
    if not instruction:
        if not sys.stdin.isatty():
            raise SystemExit("an edit instruction is required when stdin is not interactive")
        instruction = input("Describe the edit: ").strip()
    if not instruction:
        raise SystemExit("edit instruction cannot be empty")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    primary = sources[0]
    destination = (args.output or primary.with_name(
        f"{primary.stem}-qwen-edit-{stamp}.png")).expanduser().resolve()
    if destination in sources:
        raise SystemExit("output path must differ from every input image")
    ensure_service(args.no_start)
    remote_inputs = [upload_image(source) for source in sources]
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**63)
    print(f"Generating from {len(sources)} image(s) with seed {seed}...", file=sys.stderr)
    submitted = request_json("/prompt", {"prompt": workflow(
        remote_inputs, instruction, args.negative_prompt, args.steps, args.resolution, seed)})
    output_info = await_output(submitted["prompt_id"])
    download_output(output_info, destination)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
