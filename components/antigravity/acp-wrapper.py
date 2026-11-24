#!/usr/bin/env python3
"""Transparent ACP stdio wrapper that injects Homelab's global AGENTS.md + User Memory.

T3 Code launches each Antigravity instance with an isolated GEMINI_HOME and only
passes PR-linking instructions in `_meta.antigravity.systemPrompt.append`. This
wrapper sits beside `agy_acp_server.par` and `localharness_external`, inherits
stdout/stderr directly, and appends the live global instructions file (which
includes the synced User Memory block) on `session/new`, `session/load`, and
`session/resume` requests.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

SESSION_METHODS = ("session/new", "session/load", "session/resume")
SESSION_MARKERS = tuple(f'"{m}"'.encode("ascii") for m in SESSION_METHODS)
DEFAULT_INSTRUCTIONS = "/srv/state/antigravity/config/AGENTS.md"
MAX_INSTRUCTIONS_BYTES = 64 * 1024


def read_instructions(path: str | Path | None = None) -> str:
    raw_path = path if path is not None else os.environ.get("HOMELAB_ANTIGRAVITY_INSTRUCTIONS", DEFAULT_INSTRUCTIONS)
    if not raw_path:
        return ""
    try:
        data = Path(raw_path).read_bytes()
    except OSError:
        return ""
    if len(data) > MAX_INSTRUCTIONS_BYTES:
        data = data[:MAX_INSTRUCTIONS_BYTES]
    return data.decode("utf-8", errors="replace").strip()


def transform_line(line: bytes, instructions_path: str | Path | None = None) -> bytes:
    """Append global instructions to ACP session-open requests; pass all else verbatim."""
    if not any(marker in line for marker in SESSION_MARKERS):
        return line
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return line
    if not isinstance(msg, dict) or msg.get("method") not in SESSION_METHODS:
        return line
    params = msg.get("params")
    if not isinstance(params, dict):
        return line
    instructions = read_instructions(instructions_path)
    if not instructions:
        return line

    meta = params.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
        params["_meta"] = meta
    agy_meta = meta.get("antigravity")
    if not isinstance(agy_meta, dict):
        agy_meta = {}
        meta["antigravity"] = agy_meta
    sys_prompt = agy_meta.get("systemPrompt")
    if isinstance(sys_prompt, dict) and isinstance(sys_prompt.get("append"), str) and sys_prompt["append"].strip():
        existing = sys_prompt["append"].rstrip()
        if instructions not in existing:
            sys_prompt["append"] = f"{existing}\n\n{instructions}"
    else:
        agy_meta["systemPrompt"] = {"append": instructions}

    ending = b"\n" if line.endswith(b"\n") else b""
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + ending


def main() -> int:
    real_server = Path(__file__).resolve().parent / "agy_acp_server.par"
    proc = subprocess.Popen(
        [str(real_server), *sys.argv[1:]],
        stdin=subprocess.PIPE,
    )

    def forward_signal(signum, _frame):
        if proc.poll() is None:
            try:
                proc.send_signal(signum)
            except OSError:
                pass

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, forward_signal)
        except (OSError, ValueError):
            pass

    assert proc.stdin is not None
    try:
        stdin_buf = sys.stdin.buffer
        while True:
            line = stdin_buf.readline()
            if not line:
                break
            out = transform_line(line)
            try:
                proc.stdin.write(out)
                proc.stdin.flush()
            except BrokenPipeError:
                break
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass

    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
