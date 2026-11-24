#!/usr/bin/env python3
"""Server-backed on-demand cache for Xcode and iOS Simulator runtimes.

Stores compressed Xcode.app (ditto CPIO + zstd) and the matched iOS Simulator
runtime Restore payload on nixos-pc (/var/cache/apple-dev, outside Backrest
backups), and provides safe archive, verify, purge, and hydrate commands.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = os.environ.get("APPLE_DEV_CACHE_DIR", "/var/cache/apple-dev")
DEFAULT_SERVER = os.environ.get("APPLE_DEV_SERVER", "rishabh@nixos-pc")
DEFAULT_MAC = os.environ.get("APPLE_DEV_MAC", "rishabhgoel@macbook")
DEFAULT_XCODE_PATH = os.environ.get("APPLE_DEV_XCODE_PATH", "/Applications/Xcode.app")
DEFAULT_CLT_PATH = os.environ.get("APPLE_DEV_CLT_PATH", "/Library/Developer/CommandLineTools")
BRICK_ENROLLED_PATH = Path(os.environ.get("APPLE_DEV_BRICK_ENROLLED", "/etc/brick-admin.enrolled"))

MANIFEST_SCHEMA = 1
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]


def is_darwin() -> bool:
    return sys.platform == "darwin" or platform.system() == "Darwin"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{num} B"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def privileged_prefix(
    *,
    euid: int | None = None,
    enrolled_path: Path = BRICK_ENROLLED_PATH,
    which_fn: Any = shutil.which,
) -> list[str]:
    if (os.geteuid() if euid is None else euid) == 0:
        return []
    if enrolled_path.exists() and which_fn("brick-admin"):
        return ["brick-admin", "run"]
    return ["sudo"]


def run_privileged(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    full = [*privileged_prefix(), *cmd]
    return subprocess.run(full, check=check, text=True)


def ssh_cmd(host: str, remote_cmd: str) -> list[str]:
    return ["ssh", *SSH_OPTS, host, remote_cmd]


def run_capture(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def run_mac(cmd: list[str], *, mac_host: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    if mac_host:
        return run_capture(ssh_cmd(mac_host, shlex.join(cmd)), check=check)
    return run_capture(cmd, check=check)


def select_ios_runtime(
    runtimes_json: dict[str, Any],
    match_json: dict[str, Any] | None = None,
    *,
    runtime_id: str | None = None,
) -> dict[str, Any] | None:
    if runtime_id:
        for key, item in runtimes_json.items():
            if not isinstance(item, dict):
                continue
            if runtime_id in (key, item.get("identifier"), item.get("build"), item.get("runtimeIdentifier")):
                return item
        return None

    ios_runtimes = [
        item
        for item in runtimes_json.values()
        if isinstance(item, dict)
        and item.get("platformIdentifier") == "com.apple.platform.iphonesimulator"
        and item.get("state") == "Ready"
    ]
    if not ios_runtimes:
        return None

    chosen_build = None
    if isinstance(match_json, dict):
        for entry in match_json.values():
            if isinstance(entry, dict) and entry.get("platform") == "com.apple.platform.iphoneos":
                chosen_build = entry.get("chosenRuntimeBuild")
                if chosen_build:
                    break

    if chosen_build:
        for item in ios_runtimes:
            if item.get("build") == chosen_build:
                return item

    # Prefer the generic iOS runtime over device-specific variants (e.g., iPhone19-4)
    ios_runtimes.sort(
        key=lambda item: (
            "-" in str(item.get("runtimeIdentifier", "")).split("iOS-")[-1].replace("-", "", 1),
            str(item.get("lastUsedAt", "")) == "",
            str(item.get("version", "")),
            str(item.get("build", "")),
        )
    )
    return ios_runtimes[0]


def pick_iphone_devicetype(devicetypes_json: dict[str, Any]) -> str | None:
    candidates: list[tuple[tuple[int, int, str], str]] = []
    for entry in devicetypes_json.get("devicetypes", []):
        if not isinstance(entry, dict):
            continue
        ident = str(entry.get("identifier", ""))
        name = str(entry.get("name", ""))
        if not ident or entry.get("productFamily") != "iPhone":
            continue
        match = re.fullmatch(r"iPhone\s+(\d+)", name.strip())
        if match:
            candidates.append(((2, int(match.group(1)), name), ident))
        elif "iPhone" in name:
            nums = re.findall(r"\d+", name)
            score = int(nums[0]) if nums else 0
            candidates.append(((1, score, name), ident))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def inspect_mac_state(
    *,
    mac_host: str | None = None,
    xcode_path: str = DEFAULT_XCODE_PATH,
    clt_path: str = DEFAULT_CLT_PATH,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "xcode_path": xcode_path,
        "xcode_installed": False,
        "xcode": None,
        "clt_path": clt_path,
        "clt_installed": False,
        "xcode_select": None,
        "runtimes": [],
        "chosen_ios_runtime": None,
        "free_bytes": None,
    }

    probe_script = (
        "import json, os, shutil, subprocess\n"
        f"xcode = {xcode_path!r}\n"
        f"clt = {clt_path!r}\n"
        "out = {'xcode_installed': os.path.isdir(xcode), 'clt_installed': os.path.isdir(clt), 'xcode': None, 'xcode_select': None, 'runtimes_raw': {}, 'match_raw': {}, 'free_bytes': shutil.disk_usage('/').free}\n"
        "vp = os.path.join(xcode, 'Contents', 'version.plist')\n"
        "if os.path.isfile(vp):\n"
        "    r = subprocess.run(['plutil', '-convert', 'json', '-o', '-', vp], capture_output=True, text=True)\n"
        "    if r.returncode == 0:\n"
        "        d = json.loads(r.stdout)\n"
        "        out['xcode'] = {'version': d.get('CFBundleShortVersionString'), 'build': d.get('ProductBuildVersion')}\n"
        "r = subprocess.run(['xcode-select', '-p'], capture_output=True, text=True)\n"
        "if r.returncode == 0:\n"
        "    out['xcode_select'] = r.stdout.strip()\n"
        "if out['xcode_installed']:\n"
        "    r = subprocess.run(['xcrun', 'simctl', 'runtime', 'list', '-j'], capture_output=True, text=True)\n"
        "    if r.returncode == 0 and r.stdout.strip():\n"
        "        out['runtimes_raw'] = json.loads(r.stdout)\n"
        "    r = subprocess.run(['xcrun', 'simctl', 'runtime', 'match', 'list', '-j'], capture_output=True, text=True)\n"
        "    if r.returncode == 0 and r.stdout.strip():\n"
        "        out['match_raw'] = json.loads(r.stdout)\n"
        "print(json.dumps(out))\n"
    )
    proc = run_mac(["python3", "-c", probe_script], mac_host=mac_host)
    raw = json.loads(proc.stdout)
    state["xcode_installed"] = bool(raw["xcode_installed"])
    state["clt_installed"] = bool(raw["clt_installed"])
    state["xcode"] = raw["xcode"]
    state["xcode_select"] = raw["xcode_select"]
    state["free_bytes"] = raw["free_bytes"]

    runtimes_raw = raw.get("runtimes_raw") or {}
    match_raw = raw.get("match_raw") or {}
    state["runtimes"] = [v for v in runtimes_raw.values() if isinstance(v, dict)]
    state["chosen_ios_runtime"] = select_ios_runtime(runtimes_raw, match_raw)
    return state


def read_local_manifest(cache_dir: Path) -> dict[str, Any] | None:
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def read_remote_manifest(server: str, cache_dir: str) -> dict[str, Any] | None:
    remote_path = f"{cache_dir.rstrip('/')}/manifest.json"
    proc = run_capture(
        ssh_cmd(server, f"test -f {shlex.quote(remote_path)} && cat {shlex.quote(remote_path)}"),
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)


def write_manifest_atomic(cache_dir: Path, manifest: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / ".manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, cache_dir / "manifest.json")


def verify_local_cache(cache_dir: Path) -> tuple[bool, list[str]]:
    manifest = read_local_manifest(cache_dir)
    if not manifest:
        return False, [f"No manifest.json found in {cache_dir}"]
    errors: list[str] = []

    xcode = manifest.get("xcode")
    if isinstance(xcode, dict):
        rel = xcode.get("archive")
        path = cache_dir / str(rel)
        if not path.is_file():
            errors.append(f"Missing Xcode archive: {path}")
        else:
            size = path.stat().st_size
            if size != xcode.get("size_bytes"):
                errors.append(f"Size mismatch for {rel}: expected {xcode.get('size_bytes')}, got {size}")
            digest = sha256_file(path)
            if digest != xcode.get("sha256"):
                errors.append(f"SHA-256 mismatch for {rel}: expected {xcode.get('sha256')}, got {digest}")

    ios_rt = manifest.get("ios_runtime")
    if isinstance(ios_rt, dict):
        for entry in ios_rt.get("files", []):
            rel = entry.get("path")
            path = cache_dir / str(rel)
            if not path.is_file():
                errors.append(f"Missing runtime file: {path}")
                continue
            size = path.stat().st_size
            if size != entry.get("size_bytes"):
                errors.append(f"Size mismatch for {rel}: expected {entry.get('size_bytes')}, got {size}")
            digest = sha256_file(path)
            if digest != entry.get("sha256"):
                errors.append(f"SHA-256 mismatch for {rel}: expected {entry.get('sha256')}, got {digest}")

    return len(errors) == 0, errors


def check_purge_safety(
    mac_state: dict[str, Any],
    manifest: dict[str, Any] | None,
    *,
    force: bool = False,
    keep_xcode: bool = False,
    keep_runtimes: bool = False,
) -> list[str]:
    problems: list[str] = []
    if not keep_xcode and not mac_state.get("clt_installed"):
        problems.append(
            f"Xcode Command Line Tools missing at {mac_state.get('clt_path')}; "
            "install them first (xcode-select --install) so git/Nix keep working."
        )
    if force:
        return problems
    if not manifest:
        problems.append("No cached manifest found on server. Run `apple-dev archive` first (or pass --force).")
        return problems

    if not keep_xcode and mac_state.get("xcode_installed") and mac_state.get("xcode"):
        local_x = mac_state["xcode"]
        cached_x = manifest.get("xcode") or {}
        if (
            cached_x.get("version") != local_x.get("version")
            or cached_x.get("build") != local_x.get("build")
            or not cached_x.get("sha256")
        ):
            problems.append(
                f"Installed Xcode {local_x.get('version')} ({local_x.get('build')}) "
                f"does not match cached Xcode {cached_x.get('version')} ({cached_x.get('build')}). "
                "Run `apple-dev archive` first (or pass --force)."
            )

    if not keep_runtimes and mac_state.get("chosen_ios_runtime"):
        local_rt = mac_state["chosen_ios_runtime"]
        cached_rt = manifest.get("ios_runtime") or {}
        if cached_rt.get("build") != local_rt.get("build") or not cached_rt.get("files"):
            problems.append(
                f"Installed iOS runtime {local_rt.get('version')} ({local_rt.get('build')}) "
                f"does not match cached runtime {cached_rt.get('version')} ({cached_rt.get('build')}). "
                "Run `apple-dev archive` first (or pass --force)."
            )
    return problems


def stream_and_hash_to_file(stream: Any, dest: Path) -> tuple[str, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    total = 0
    try:
        with part.open("wb") as handle:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                handle.write(chunk)
                total += len(chunk)
        os.replace(part, dest)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), total


def archive_from_mac_to_local(
    *,
    mac_host: str,
    cache_dir: Path,
    runtime_id: str | None = None,
    skip_xcode: bool = False,
    skip_runtime: bool = False,
) -> dict[str, Any]:
    mac_state = inspect_mac_state(mac_host=mac_host)
    manifest = read_local_manifest(cache_dir) or {"schema": MANIFEST_SCHEMA}
    manifest["schema"] = MANIFEST_SCHEMA
    manifest["updated_at"] = now_iso()

    if not skip_xcode:
        if not mac_state["xcode_installed"] or not mac_state["xcode"]:
            raise RuntimeError(f"Xcode is not installed at {mac_state['xcode_path']} on {mac_host}")
        ver = mac_state["xcode"]["version"]
        build = mac_state["xcode"]["build"]
        rel_archive = f"xcode/Xcode-{ver}-{build}.cpio.zst"
        dest = cache_dir / rel_archive
        cached_x = manifest.get("xcode") or {}
        if (
            dest.is_file()
            and cached_x.get("archive") == rel_archive
            and cached_x.get("size_bytes") == dest.stat().st_size
            and sha256_file(dest) == cached_x.get("sha256")
        ):
            print(f"Xcode {ver} ({build}) already archived and verified at {dest}", file=sys.stderr)
        else:
            print(f"Archiving Xcode {ver} ({build}) from {mac_host} -> {dest} ...", file=sys.stderr)
            has_remote_zstd = (
                run_capture(ssh_cmd(mac_host, "command -v zstd >/dev/null 2>&1"), check=False).returncode == 0
            )
            if has_remote_zstd:
                remote = f"ditto -c --keepParent {shlex.quote(mac_state['xcode_path'])} - | zstd -T0 -3 -c"
                ssh_proc = subprocess.Popen(ssh_cmd(mac_host, remote), stdout=subprocess.PIPE)
                assert ssh_proc.stdout is not None
                digest, size = stream_and_hash_to_file(ssh_proc.stdout, dest)
                rc = ssh_proc.wait()
                if rc != 0:
                    dest.unlink(missing_ok=True)
                    raise RuntimeError(f"Remote Xcode archive stream failed with exit code {rc}")
            else:
                remote = f"ditto -c --keepParent {shlex.quote(mac_state['xcode_path'])} -"
                ssh_proc = subprocess.Popen(ssh_cmd(mac_host, remote), stdout=subprocess.PIPE)
                zstd_proc = subprocess.Popen(["zstd", "-T0", "-3", "-c"], stdin=ssh_proc.stdout, stdout=subprocess.PIPE)
                assert ssh_proc.stdout is not None
                ssh_proc.stdout.close()
                assert zstd_proc.stdout is not None
                digest, size = stream_and_hash_to_file(zstd_proc.stdout, dest)
                zrc = zstd_proc.wait()
                src = ssh_proc.wait()
                if src != 0 or zrc != 0:
                    dest.unlink(missing_ok=True)
                    raise RuntimeError(f"Xcode archive failed (ssh={src}, zstd={zrc})")
            manifest["xcode"] = {
                "version": ver,
                "build": build,
                "archive": rel_archive,
                "sha256": digest,
                "size_bytes": size,
            }
            write_manifest_atomic(cache_dir, manifest)
            print(f"Archived Xcode {ver} ({build}): {format_bytes(size)} sha256={digest[:12]}...", file=sys.stderr)

    if not skip_runtime:
        runtimes_raw = {r["identifier"]: r for r in mac_state["runtimes"] if "identifier" in r}
        chosen = select_ios_runtime(runtimes_raw, runtime_id=runtime_id) if runtime_id else mac_state["chosen_ios_runtime"]
        if not chosen:
            raise RuntimeError("No Ready iOS Simulator runtime found on Mac.")
        rt_ver = chosen["version"]
        rt_build = chosen["build"]
        rt_ident = chosen.get("runtimeIdentifier", "")
        asset_path = chosen["path"]
        restore_remote = f"{asset_path.rstrip('/')}/Restore"

        list_script = (
            "import json, os\n"
            f"root = {restore_remote!r}\n"
            "items = []\n"
            "for dirpath, _, filenames in os.walk(root):\n"
            "    for name in sorted(filenames):\n"
            "        full = os.path.join(dirpath, name)\n"
            "        rel = os.path.relpath(full, root)\n"
            "        items.append({'rel': rel, 'size': os.path.getsize(full)})\n"
            "print(json.dumps(items))\n"
        )
        files_meta = json.loads(run_mac(["python3", "-c", list_script], mac_host=mac_host).stdout)
        if not files_meta:
            raise RuntimeError(f"No files found in {restore_remote} on {mac_host}")

        rel_dir = f"runtimes/iOS-{rt_ver}-{rt_build}/Restore"
        existing_by_path = {
            f["path"]: f for f in (manifest.get("ios_runtime") or {}).get("files", []) if isinstance(f, dict)
        }
        archived_files: list[dict[str, Any]] = []
        dmg_relpath: str | None = None

        print(f"Archiving iOS {rt_ver} ({rt_build}) runtime from {mac_host} ...", file=sys.stderr)
        for item in sorted(files_meta, key=lambda x: x["rel"]):
            rel_inside = item["rel"]
            rel_cache = f"{rel_dir}/{rel_inside}"
            dest = cache_dir / rel_cache
            if rel_inside.endswith(".dmg") and "/" not in rel_inside:
                dmg_relpath = rel_cache

            prev = existing_by_path.get(rel_cache)
            if (
                dest.is_file()
                and prev
                and dest.stat().st_size == item["size"]
                and prev.get("size_bytes") == item["size"]
                and sha256_file(dest) == prev.get("sha256")
            ):
                print(f"  Verified existing {rel_cache} ({format_bytes(item['size'])})", file=sys.stderr)
                archived_files.append(prev)
                continue

            remote_file = f"{restore_remote}/{rel_inside}"
            print(f"  Transferring {rel_cache} ({format_bytes(item['size'])}) ...", file=sys.stderr)
            ssh_proc = subprocess.Popen(ssh_cmd(mac_host, f"cat {shlex.quote(remote_file)}"), stdout=subprocess.PIPE)
            assert ssh_proc.stdout is not None
            digest, size = stream_and_hash_to_file(ssh_proc.stdout, dest)
            rc = ssh_proc.wait()
            if rc != 0 or size != item["size"]:
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"Transfer failed for {rel_inside} (rc={rc}, expected={item['size']}, got={size})")
            archived_files.append({"path": rel_cache, "sha256": digest, "size_bytes": size})

        if not dmg_relpath:
            raise RuntimeError(f"No top-level .dmg found inside {restore_remote}")

        manifest["ios_runtime"] = {
            "version": rt_ver,
            "build": rt_build,
            "runtime_identifier": rt_ident,
            "dir": rel_dir,
            "dmg_relpath": dmg_relpath,
            "files": archived_files,
        }
        write_manifest_atomic(cache_dir, manifest)
        print(f"Archived iOS {rt_ver} ({rt_build}) runtime ({len(archived_files)} files).", file=sys.stderr)

    return manifest


def archive_from_local_mac_to_server(
    *,
    server: str,
    cache_dir: str,
    runtime_id: str | None = None,
    skip_xcode: bool = False,
    skip_runtime: bool = False,
) -> None:
    cmd = ["apple-dev", "archive", "--cache-dir", cache_dir]
    if runtime_id:
        cmd.extend(["--runtime-id", runtime_id])
    if skip_xcode:
        cmd.append("--skip-xcode")
    if skip_runtime:
        cmd.append("--skip-runtime")
    subprocess.run(ssh_cmd(server, shlex.join(cmd)), check=True)


def hydrate_on_mac(
    *,
    server: str,
    cache_dir: str,
    xcode_path: str = DEFAULT_XCODE_PATH,
    skip_xcode: bool = False,
    skip_runtime: bool = False,
    no_device: bool = False,
) -> None:
    if not is_darwin():
        raise RuntimeError("`apple-dev hydrate` must be run on macOS.")

    manifest = read_remote_manifest(server, cache_dir)
    if not manifest:
        raise RuntimeError(f"No manifest.json found at {server}:{cache_dir}")

    mac_state = inspect_mac_state(xcode_path=xcode_path)

    if not skip_xcode:
        cached_x = manifest.get("xcode")
        if not isinstance(cached_x, dict):
            raise RuntimeError("Manifest has no cached Xcode entry.")
        local_x = mac_state.get("xcode") or {}
        if (
            mac_state["xcode_installed"]
            and local_x.get("version") == cached_x.get("version")
            and local_x.get("build") == cached_x.get("build")
        ):
            print(f"Xcode {cached_x['version']} ({cached_x['build']}) already installed at {xcode_path}.", file=sys.stderr)
        else:
            remote_archive = f"{cache_dir.rstrip('/')}/{cached_x['archive']}"
            expected_sha = str(cached_x["sha256"])
            print(
                f"Hydrating Xcode {cached_x['version']} ({cached_x['build']}) "
                f"({format_bytes(int(cached_x['size_bytes']))}) from {server} ...",
                file=sys.stderr,
            )
            staging_root = Path(tempfile.mkdtemp(prefix="apple-dev-xcode-"))
            try:
                ssh_proc = subprocess.Popen(ssh_cmd(server, f"cat {shlex.quote(remote_archive)}"), stdout=subprocess.PIPE)
                zstd_proc = subprocess.Popen(["zstd", "-d", "-c"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                ditto_proc = subprocess.Popen(["ditto", "-x", "-", str(staging_root)], stdin=zstd_proc.stdout)
                assert ssh_proc.stdout is not None and zstd_proc.stdin is not None and zstd_proc.stdout is not None
                zstd_proc.stdout.close()

                digest = hashlib.sha256()
                try:
                    while chunk := ssh_proc.stdout.read(1024 * 1024):
                        digest.update(chunk)
                        zstd_proc.stdin.write(chunk)
                finally:
                    zstd_proc.stdin.close()

                drc = ditto_proc.wait()
                zrc = zstd_proc.wait()
                src = ssh_proc.wait()
                actual_sha = digest.hexdigest()
                if src != 0 or zrc != 0 or drc != 0:
                    raise RuntimeError(f"Xcode hydrate stream failed (ssh={src}, zstd={zrc}, ditto={drc})")
                if actual_sha != expected_sha:
                    raise RuntimeError(f"Xcode archive SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")

                extracted = staging_root / "Xcode.app"
                if not extracted.is_dir():
                    raise RuntimeError(f"Extracted archive did not produce {extracted}")

                install_script = (
                    "set -euo pipefail; "
                    f"rm -rf {shlex.quote(xcode_path)}; "
                    f"mv {shlex.quote(str(extracted))} {shlex.quote(xcode_path)}; "
                    f"chown -R root:wheel {shlex.quote(xcode_path)}; "
                    f"xcode-select -s {shlex.quote(xcode_path + '/Contents/Developer')}; "
                    "xcodebuild -runFirstLaunch"
                )
                run_privileged(["/bin/bash", "-c", install_script])
                print(f"Installed Xcode {cached_x['version']} ({cached_x['build']}) to {xcode_path}.", file=sys.stderr)
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)

    if not skip_runtime:
        cached_rt = manifest.get("ios_runtime")
        if not isinstance(cached_rt, dict):
            raise RuntimeError("Manifest has no cached iOS runtime entry.")
        mac_state = inspect_mac_state(xcode_path=xcode_path)
        already_installed = any(
            rt.get("build") == cached_rt.get("build") and rt.get("state") == "Ready"
            for rt in mac_state.get("runtimes", [])
        )
        if already_installed:
            print(f"iOS {cached_rt['version']} ({cached_rt['build']}) runtime already installed.", file=sys.stderr)
        else:
            staging_root = Path(tempfile.mkdtemp(prefix="apple-dev-runtime-"))
            try:
                print(f"Hydrating iOS {cached_rt['version']} ({cached_rt['build']}) runtime from {server} ...", file=sys.stderr)
                for entry in cached_rt["files"]:
                    rel = str(entry["path"])
                    remote_file = f"{cache_dir.rstrip('/')}/{rel}"
                    local_file = staging_root / rel
                    print(f"  Fetching {Path(rel).name} ({format_bytes(int(entry['size_bytes']))}) ...", file=sys.stderr)
                    ssh_proc = subprocess.Popen(ssh_cmd(server, f"cat {shlex.quote(remote_file)}"), stdout=subprocess.PIPE)
                    assert ssh_proc.stdout is not None
                    digest, size = stream_and_hash_to_file(ssh_proc.stdout, local_file)
                    rc = ssh_proc.wait()
                    if rc != 0 or size != int(entry["size_bytes"]) or digest != entry["sha256"]:
                        raise RuntimeError(f"Verification failed for {rel} (rc={rc}, sha256={digest})")

                dmg_path = staging_root / str(cached_rt["dmg_relpath"])
                print(f"Registering runtime via xcrun simctl runtime add --move {dmg_path.name} ...", file=sys.stderr)
                run_privileged(["/usr/bin/xcrun", "simctl", "runtime", "add", "--move", str(dmg_path)])
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)

        if not no_device:
            devices_raw = json.loads(run_capture(["xcrun", "simctl", "list", "devices", "-j"]).stdout)
            rt_ident = cached_rt.get("runtime_identifier")
            existing = devices_raw.get("devices", {}).get(rt_ident, []) if rt_ident else []
            if not existing and rt_ident:
                devicetypes = json.loads(run_capture(["xcrun", "simctl", "list", "devicetypes", "-j"]).stdout)
                device_type = pick_iphone_devicetype(devicetypes)
                if device_type:
                    created = run_capture(["xcrun", "simctl", "create", "iPhone", device_type, rt_ident])
                    print(f"Created default iPhone simulator ({created.stdout.strip()}).", file=sys.stderr)


def purge_on_mac(
    *,
    server: str,
    cache_dir: str,
    xcode_path: str = DEFAULT_XCODE_PATH,
    clt_path: str = DEFAULT_CLT_PATH,
    force: bool = False,
    keep_xcode: bool = False,
    keep_runtimes: bool = False,
) -> None:
    if not is_darwin():
        raise RuntimeError("`apple-dev purge` must be run on macOS.")

    mac_state = inspect_mac_state(xcode_path=xcode_path, clt_path=clt_path)
    before_free = int(mac_state["free_bytes"] or 0)
    manifest = None if force else read_remote_manifest(server, cache_dir)
    problems = check_purge_safety(
        mac_state,
        manifest,
        force=force,
        keep_xcode=keep_xcode,
        keep_runtimes=keep_runtimes,
    )
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)

    if not keep_runtimes:
        subprocess.run(["xcrun", "simctl", "shutdown", "all"], check=False)
        subprocess.run(["xcrun", "simctl", "delete", "all"], check=False)
        if mac_state.get("runtimes"):
            run_privileged(["/usr/bin/xcrun", "simctl", "runtime", "delete", "all"])
        home = Path.home()
        for user_cache in (
            home / "Library/Developer/CoreSimulator",
            home / "Library/Developer/Xcode/DerivedData",
            home / "Library/Caches/com.apple.dt.Xcode",
        ):
            if user_cache.exists():
                shutil.rmtree(user_cache, ignore_errors=True)

    if not keep_xcode:
        purge_script = (
            "set -euo pipefail; "
            f"rm -rf {shlex.quote(xcode_path)}; "
            f"xcode-select -s {shlex.quote(clt_path)}"
        )
        run_privileged(["/bin/bash", "-c", purge_script])

    after_free = shutil.disk_usage("/").free
    freed = max(0, after_free - before_free)
    print(f"Purge complete. Free space on /: {format_bytes(before_free)} -> {format_bytes(after_free)} (+{format_bytes(freed)}).")


def cmd_status(args: argparse.Namespace) -> int:
    report: dict[str, Any] = {"platform": sys.platform}
    if is_darwin():
        report["mac"] = inspect_mac_state(xcode_path=args.xcode_path, clt_path=args.clt_path)
        report["cache"] = read_remote_manifest(args.server, args.cache_dir)
    else:
        cache_dir = Path(args.cache_dir)
        report["cache_dir"] = str(cache_dir)
        report["cache"] = read_local_manifest(cache_dir)
        if args.mac:
            report["mac"] = inspect_mac_state(
                mac_host=args.mac_host,
                xcode_path=args.xcode_path,
                clt_path=args.clt_path,
            )

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    mac = report.get("mac")
    if isinstance(mac, dict):
        x = mac.get("xcode")
        print(f"Mac Xcode:        {x['version'] + ' (' + x['build'] + ')' if x else 'not installed'}")
        print(f"Mac xcode-select: {mac.get('xcode_select')}")
        print(f"Mac CLT:          {'installed' if mac.get('clt_installed') else 'MISSING'}")
        chosen = mac.get("chosen_ios_runtime")
        print(
            f"Mac iOS runtime:  {chosen['version'] + ' (' + chosen['build'] + ')' if chosen else 'none'} "
            f"({len(mac.get('runtimes', []))} total disk images)"
        )
        if mac.get("free_bytes") is not None:
            print(f"Mac free space:   {format_bytes(int(mac['free_bytes']))}")

    cache = report.get("cache")
    if isinstance(cache, dict):
        cx = cache.get("xcode")
        cr = cache.get("ios_runtime")
        print(f"Cached updated:  {cache.get('updated_at')}")
        if isinstance(cx, dict):
            print(f"Cached Xcode:    {cx['version']} ({cx['build']}) — {format_bytes(int(cx['size_bytes']))}")
        if isinstance(cr, dict):
            total_rt = sum(int(f["size_bytes"]) for f in cr.get("files", []))
            print(f"Cached iOS RT:   {cr['version']} ({cr['build']}) — {format_bytes(total_rt)} ({len(cr.get('files', []))} files)")
    else:
        print(f"Server cache:    empty ({args.cache_dir})")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    if is_darwin():
        proc = subprocess.run(
            ssh_cmd(args.server, shlex.join(["apple-dev", "verify", "--cache-dir", args.cache_dir])),
            check=False,
        )
        return proc.returncode
    ok, errors = verify_local_cache(Path(args.cache_dir))
    if not ok:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"Cache verified OK: {args.cache_dir}")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    if is_darwin():
        archive_from_local_mac_to_server(
            server=args.server,
            cache_dir=args.cache_dir,
            runtime_id=args.runtime_id,
            skip_xcode=args.skip_xcode,
            skip_runtime=args.skip_runtime,
        )
        return 0
    archive_from_mac_to_local(
        mac_host=args.mac_host,
        cache_dir=Path(args.cache_dir),
        runtime_id=args.runtime_id,
        skip_xcode=args.skip_xcode,
        skip_runtime=args.skip_runtime,
    )
    return 0


def cmd_hydrate(args: argparse.Namespace) -> int:
    hydrate_on_mac(
        server=args.server,
        cache_dir=args.cache_dir,
        xcode_path=args.xcode_path,
        skip_xcode=args.skip_xcode,
        skip_runtime=args.skip_runtime,
        no_device=args.no_device,
    )
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    purge_on_mac(
        server=args.server,
        cache_dir=args.cache_dir,
        xcode_path=args.xcode_path,
        clt_path=args.clt_path,
        force=args.force,
        keep_xcode=args.keep_xcode,
        keep_runtimes=args.keep_runtimes,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apple-dev",
        description="Server-backed cache for on-demand Xcode and iOS Simulator deployment.",
    )
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="Server cache directory")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="SSH target for server cache (from Mac)")
    parser.add_argument("--mac-host", default=DEFAULT_MAC, help="SSH target for MacBook (from server)")
    parser.add_argument("--xcode-path", default=DEFAULT_XCODE_PATH, help="Path to Xcode.app on Mac")
    parser.add_argument("--clt-path", default=DEFAULT_CLT_PATH, help="Path to Xcode Command Line Tools on Mac")

    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Show Mac and server cache status")
    p_status.add_argument("--json", action="store_true", help="Emit JSON")
    p_status.add_argument("--mac", action="store_true", help="Also probe Mac over SSH when run on server")
    p_status.set_defaults(func=cmd_status)

    p_verify = sub.add_parser("verify", help="Verify SHA-256 checksums of cached artifacts")
    p_verify.set_defaults(func=cmd_verify)

    p_archive = sub.add_parser("archive", help="Archive Mac Xcode.app and matched iOS runtime to server cache")
    p_archive.add_argument("--runtime-id", help="Override iOS runtime UUID/build to archive")
    p_archive.add_argument("--skip-xcode", action="store_true", help="Skip archiving Xcode.app")
    p_archive.add_argument("--skip-runtime", action="store_true", help="Skip archiving iOS Simulator runtime")
    p_archive.set_defaults(func=cmd_archive)

    p_hydrate = sub.add_parser("hydrate", help="Restore Xcode.app and iOS Simulator runtime on Mac from server cache")
    p_hydrate.add_argument("--skip-xcode", action="store_true", help="Skip restoring Xcode.app")
    p_hydrate.add_argument("--skip-runtime", action="store_true", help="Skip restoring iOS Simulator runtime")
    p_hydrate.add_argument("--no-device", action="store_true", help="Do not auto-create default iPhone simulator")
    p_hydrate.set_defaults(func=cmd_hydrate)

    p_purge = sub.add_parser("purge", help="Remove Xcode.app, simulator runtimes, and CoreSimulator caches from Mac")
    p_purge.add_argument("--force", action="store_true", help="Purge even if server cache does not match")
    p_purge.add_argument("--keep-xcode", action="store_true", help="Keep /Applications/Xcode.app")
    p_purge.add_argument("--keep-runtimes", action="store_true", help="Keep installed simulator runtimes")
    p_purge.set_defaults(func=cmd_purge)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
