#!/usr/bin/env python3
"""Curated NASA wallpapers; AppKit is imported only when changing a Mac desktop."""
import argparse
import fcntl
import hashlib
import json
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


def image_path(directory, identity):
    return directory / f"space-{hashlib.sha256(identity.encode()).hexdigest()[:32]}.jpg"


def download_image(entry, directory, cfg):
    """Bound network/disk usage, validate decoded pixels, and atomically publish a JPEG."""
    target = image_path(directory, entry["id"])
    if target.exists():
        return target
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
            image.thumbnail((5120, 5120), Image.Resampling.LANCZOS)
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".space-render-", delete=False) as rendered:
                output_path = Path(rendered.name)
            # 5K retains more than the MacBook panel's native resolution.
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
    if not force and (state.get("paused") or time.time() - state.get("changedAt", 0) < cfg["intervalSeconds"]):
        return False
    by_id = {e["id"]: e for e in entries}
    current_id = state.get("current", {}).get("id")
    remaining = [identity for identity in state.get("remaining", []) if identity in by_id and identity != current_id]
    if not remaining:
        remaining = list(by_id)
        random.shuffle(remaining)
        # A new shuffle cycle should not immediately repeat the last image.
        remaining.sort(key=lambda identity: identity == current_id)
    candidates = [by_id[identity] for identity in remaining if identity != current_id]
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
            path = image_path(directory, entry["id"])
            if path.exists():
                chosen, target = entry, path
                break
    if chosen is None:
        raise RuntimeError("No new image available; keeping the existing desktop")
    protected = {target}
    if current_id:
        protected.add(image_path(directory, current_id))
    prune(directory, protected, cfg["cacheImages"])
    setter(target)
    target.touch()
    state.update(current={**chosen, "file": str(target)}, changedAt=time.time(),
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
        rotate(cfg, entries, state, state_path, force=args.action == "next")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"space-wallpaper: {error}", file=sys.stderr)
        sys.exit(1)
