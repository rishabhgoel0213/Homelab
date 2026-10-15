#!/usr/bin/env python3
"""Curated NASA wallpapers with display-aware resolution checks and crop-to-fill."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageOps

MIB = 1024 * 1024
Image.MAX_IMAGE_PIXELS = 160_000_000


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.close()
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def validate_catalogue(entries):
    ids = set()
    for entry in entries:
        identity = entry["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identity) or identity in ids:
            raise ValueError(f"Invalid or duplicate image id: {identity}")
        ids.add(identity)
        for field in ("url", "source"):
            url = urllib.parse.urlsplit(entry[field])
            if (url.scheme != "https" or url.hostname not in {
                "assets.science.nasa.gov", "images-assets.nasa.gov",
                "science.nasa.gov", "images.nasa.gov",
            } or url.username or url.password):
                raise ValueError(f"Unapproved NASA URL: {entry[field]}")
        if min(entry["width"], entry["height"]) < 2160 or max(entry["width"], entry["height"]) < 3840:
            raise ValueError(f"Image is below the resolution floor: {identity}")
        if not entry["title"].strip() or not entry["description"].strip():
            raise ValueError(f"Missing image context: {identity}")
    if len(ids) < 2:
        raise ValueError("The catalogue needs at least two images")
    return entries


def parse_display_targets(report):
    """Use physical pixels, and the larger backing buffer when macOS scales it."""
    targets = []

    def dimensions(value):
        match = re.search(r"(\d+)\s*[x×]\s*(\d+)", str(value))
        return tuple(map(int, match.groups())) if match else None

    for gpu in report.get("SPDisplaysDataType", []):
        for display in gpu.get("spdisplays_ndrvs", []):
            if display.get("spdisplays_online") == "spdisplays_no":
                continue
            native = dimensions(display.get("spdisplays_pixelresolution", ""))
            backing = dimensions(display.get("_spdisplays_pixels", ""))
            # Do not mistake the logical “looks like” resolution for physical pixels.
            if native is None:
                raise RuntimeError(f"Cannot determine native pixels for {display.get('_name', 'display')}")
            if backing and (native[0] > native[1]) != (backing[0] > backing[1]):
                native = native[::-1]  # A physically rotated external display.
            backing = backing or native
            targets.append((max(native[0], backing[0]), max(native[1], backing[1])))
    if not targets or any(min(size) <= 0 for size in targets):
        raise RuntimeError("No connected display with a valid native resolution")
    return sorted(set(targets))


def display_targets():
    try:
        result = subprocess.run(
            ["/usr/sbin/system_profiler", "SPDisplaysDataType", "-json"],
            check=True, capture_output=True, text=True, timeout=30,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        return parse_display_targets(json.loads(result.stdout))
    except (subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot inspect display pixels: {error}") from error


def crop_dimensions(size, target):
    """Largest crop of the source at the display's aspect ratio, without scaling."""
    width, height = size
    target_width, target_height = target
    if width * target_height > height * target_width:
        return height * target_width // target_height, height
    return width, width * target_height // target_width


def meets_displays(size, targets):
    return all(
        crop_dimensions(size, target)[0] >= target[0]
        and crop_dimensions(size, target)[1] >= target[1]
        for target in targets
    )


def cached_image(entry, directory, cfg):
    path = image_path(directory, entry["id"])
    try:
        with Image.open(path) as image:
            if image.format != "JPEG" or not meets_displays(image.size, cfg["displays"]):
                return None
            image.load()
        return path
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def image_path(directory, identity):
    return directory / f"space-{hashlib.sha256(identity.encode()).hexdigest()[:32]}.jpg"


def download_image(entry, directory, cfg):
    """Bound network/disk usage, validate decoded pixels, and atomically publish a JPEG."""
    target = image_path(directory, entry["id"])
    cached = cached_image(entry, directory, cfg)
    if cached is not None:
        return cached
    raw_path = output_path = None
    try:
        request = urllib.request.Request(entry["url"], headers={"User-Agent": "Homelab-Space-Wallpaper/1.0"})
        deadline = time.monotonic() + 90
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".space-download-", delete=False) as raw:
            raw_path = Path(raw.name)
            with urllib.request.urlopen(request, timeout=20) as response:
                if urllib.parse.urlsplit(response.url).scheme != "https":
                    raise ValueError("Refusing an insecure image redirect")
                limit = cfg["maxDownloadMiB"] * MIB
                if int(response.headers.get("Content-Length", "0")) > limit:
                    raise ValueError("NASA download exceeds the configured size limit")
                total = 0
                while chunk := response.read(256 * 1024):
                    total += len(chunk)
                    if total > limit or time.monotonic() > deadline:
                        raise ValueError("NASA download exceeded size or time limit")
                    raw.write(chunk)
        with Image.open(raw_path) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("Expected a JPEG or PNG photograph")
            if min(image.size) < 2160 or max(image.size) < 3840:
                raise ValueError("Downloaded image is below the resolution floor")
            image.load()
            image = ImageOps.exif_transpose(image).convert("RGB")
            if not meets_displays(image.size, cfg["displays"]):
                raise ValueError("Cropped image would need upscaling to fill the display")
            # Keep sufficient source pixels even with a portrait source or 6K display.
            required_scale = max(max(w / image.width, h / image.height) for w, h in cfg["displays"])
            scale = min(1, max(5120 / max(image.size), required_scale))
            if scale < 1:
                image = image.resize((math.ceil(image.width * scale), math.ceil(image.height * scale)), Image.Resampling.LANCZOS)
            if not meets_displays(image.size, cfg["displays"]):
                raise ValueError("Rendered crop is below the display resolution")
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".space-render-", delete=False) as rendered:
                output_path = Path(rendered.name)
            # The final cached pixels, not only catalogue metadata, must qualify.
            image.save(output_path, "JPEG", quality=93, optimize=True)
            if output_path.stat().st_size > cfg["maxImageMiB"] * MIB:
                raise ValueError("Rendered image exceeds the cache entry size limit")
        output_path.replace(target)
        return target
    finally:
        for path in (raw_path, output_path):
            if path is not None:
                path.unlink(missing_ok=True)


def set_desktop(path):
    helper = os.environ.get("SPACE_WALLPAPER_DESKTOP_HELPER", str(Path(__file__).with_name("set-desktop.js")))
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", helper, str(path)],
            capture_output=True, text=True, timeout=45,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("macOS timed out while setting the wallpaper") from error
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "macOS could not set the wallpaper")


def prune(directory, protected, limit):
    # Only files owned by this component; user pictures in the folder are untouched.
    files = [p for p in directory.glob("space-*.jpg") if re.fullmatch(r"space-[a-f0-9]{32}\.jpg", p.name)]
    files.sort(key=lambda p: (p in protected, p.stat().st_mtime), reverse=True)
    for path in files[limit:]:
        path.unlink()


def rotate(cfg, entries, state, state_path, force=False, setter=set_desktop):
    directory = Path(cfg["directory"]).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    profile = {"version": 1, "mode": "fill", "targets": [list(t) for t in cfg["displays"]]}
    if not force and state.get("paused"):
        return False
    if (not force and state.get("displayProfile") == profile
            and time.time() - state.get("changedAt", 0) < cfg["intervalSeconds"]):
        return False
    entries = [e for e in entries if meets_displays((e["width"], e["height"]), cfg["displays"])]
    if not entries:
        raise RuntimeError("No catalogue image has enough pixels after cropping for the connected displays")
    by_id = {e["id"]: e for e in entries}
    current_id = state.get("current", {}).get("id")
    remaining = [identity for identity in state.get("remaining", []) if identity in by_id and identity != current_id]
    if not remaining:
        remaining = list(by_id)
        random.shuffle(remaining)
        # A new shuffle cycle should not immediately repeat the last image.
        remaining.sort(key=lambda identity: identity == current_id)
    candidates = [by_id[identity] for identity in remaining if identity != current_id]
    if not candidates and current_id in by_id:
        candidates = [by_id[current_id]]  # Still apply a new crop/display policy with a one-image pool.
    chosen = target = None
    for entry in candidates[:3]:
        try:
            target = download_image(entry, directory, cfg)
            chosen = entry
            break
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            print(f"{entry['id']}: {error}", file=sys.stderr)
    if chosen is None:
        # Network failure: prefer unused cached entries, then any cached alternative.
        offline = candidates + [e for e in entries if e["id"] != current_id]
        for entry in offline:
            path = cached_image(entry, directory, cfg)
            if path is not None:
                chosen, target = entry, path
                break
    if chosen is None:
        raise RuntimeError("No new image available; keeping the existing desktop")
    protected = {target}
    if current_id:
        protected.add(Path(state["current"].get("file", image_path(directory, current_id))))
    prune(directory, protected, cfg["cacheImages"])
    setter(target)
    target.touch()
    state.update(current={**chosen, "file": str(target)}, changedAt=time.time(),
                 displayProfile=profile, eligibleImages=len(entries),
                 remaining=[i for i in remaining if i != chosen["id"]])
    atomic_json(state_path, state)
    prune(directory, {target}, cfg["cacheImages"])
    return True


def menu(state, cfg):
    current = state.get("current", {})
    # SwiftBar control characters must never come from image metadata.
    def clean(value):
        return re.sub(r"[\r\n|]", " ", str(value))
    command = "/run/current-system/sw/bin/space-wallpaper"
    print("✦ | tooltip=Space wallpapers")
    print("---")
    print(clean(current.get("title", "Waiting for the first NASA image")) + " | length=80")
    if current:
        print(f"Read about this image | href={current['source']}")
    print("---")
    for title, action in [("Next image", "next"), ("Resume hourly rotation" if state.get("paused") else "Pause rotation", "resume" if state.get("paused") else "pause")]:
        print(f"{title} | bash={command} param1={action} terminal=false refresh=true")
    folder = Path(cfg["directory"]).expanduser().as_uri()
    print(f"Open wallpaper folder | href={folder}")
    print(f"{cfg['cacheImages']} images cached at most · every {cfg['intervalSeconds'] // 60} minutes | color=gray")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("SPACE_WALLPAPER_CONFIG", "/etc/space-wallpaper/config.json"))
    parser.add_argument("action", choices=["tick", "next", "pause", "resume", "status", "menu", "source", "validate"], nargs="?", default="status")
    args = parser.parse_args()
    cfg = read_json(Path(args.config), {})
    entries = validate_catalogue(read_json(Path(cfg["catalogue"]), []))
    if args.action == "validate":
        print(f"Validated {len(entries)} NASA images")
        return
    support = Path(cfg["stateDirectory"]).expanduser()
    support.mkdir(parents=True, exist_ok=True)
    state_path = support / "state.json"
    if args.action in {"status", "menu", "source"}:
        state = read_json(state_path, {})
        if args.action == "menu":
            menu(state, cfg)
        elif args.action == "source":
            if not state.get("current"):
                raise RuntimeError("No wallpaper has been selected yet")
            subprocess.run(["/usr/bin/open", state["current"]["source"]], check=True)
        else:
            print(json.dumps(state, indent=2, ensure_ascii=False))
        return
    with (support / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state = read_json(state_path, {})
        if args.action in {"pause", "resume"}:
            state["paused"] = args.action == "pause"
            atomic_json(state_path, state)
            if state["paused"]:
                return
        cfg["displays"] = display_targets()
        rotate(cfg, entries, state, state_path, force=args.action == "next")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"space-wallpaper: {error}", file=sys.stderr)
        sys.exit(1)
