#!/usr/bin/env python3
"""Safely capture and locally transcribe a short Remote Phone microphone clip."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import wave

import websocket


DEFAULT_HOST = "pixel-10"
DEFAULT_PORT = 8080
DEFAULT_SECRET_FILE = "/run/secrets/remote-phone-token"
MAX_DURATION_SECONDS = 60.0
SAMPLE_RATE = 16_000
CHUNK_MS = 20
SAMPLE_WIDTH = 2
CHANNELS = 1
MAX_TOKEN_BYTES = 4096
TAILNETS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)
REMOTE_CLOSE_ERRORS = {
    4010: "authentication failed",
    4011: "microphone capability is disabled on the phone",
    4012: "the phone rejected the microphone configuration",
    4013: "the microphone resource is busy",
    4014: "the phone could not start its microphone",
    4015: "the phone rejected the peer as outside the tailnet",
}


class ToolError(RuntimeError):
    """A safe operator-facing error that contains no credential material."""


def bounded_duration(value: str) -> float:
    try:
        duration = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("duration must be a number of seconds") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise argparse.ArgumentTypeError("duration must be greater than zero")
    if duration > MAX_DURATION_SECONDS:
        raise argparse.ArgumentTypeError(
            f"duration cannot exceed {MAX_DURATION_SECONDS:g} seconds"
        )
    return duration


def is_tailnet_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return any(address in network for network in TAILNETS)


def resolve_tailnet_address(host: str, port: int) -> str:
    try:
        results = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise ToolError(
            f"cannot resolve {host!r}; confirm the phone and Tailscale DNS are available"
        ) from exc

    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for result in results:
        raw_address = result[4][0].split("%", maxsplit=1)[0]
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError:
            continue
        if is_tailnet_address(str(address)) and address not in candidates:
            candidates.append(address)

    if not candidates:
        raise ToolError(
            f"{host!r} did not resolve to a Tailscale address; refusing to send credentials"
        )

    candidates.sort(key=lambda address: (address.version != 4, str(address)))
    return str(candidates[0])


def validate_secret_file(path: Path) -> None:
    try:
        metadata = path.stat()
    except FileNotFoundError as exc:
        raise ToolError(
            f"runtime secret is unavailable at {path}; deploy the NixOS configuration "
            "after promoting the Bitwarden token"
        ) from exc
    except OSError as exc:
        raise ToolError(f"cannot inspect runtime secret at {path}") from exc

    if not stat.S_ISREG(metadata.st_mode):
        raise ToolError(f"runtime secret at {path} is not a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ToolError(f"runtime secret at {path} is not private (expected mode 0400)")
    if not os.access(path, os.R_OK):
        raise ToolError(f"runtime secret at {path} is not readable by this user")


def read_token(secret_file: Path, token_stdin: bool) -> str:
    if token_stdin:
        token_bytes = sys.stdin.buffer.read(MAX_TOKEN_BYTES + 1)
        source = "standard input"
    else:
        validate_secret_file(secret_file)
        try:
            with secret_file.open("rb") as handle:
                token_bytes = handle.read(MAX_TOKEN_BYTES + 1)
        except OSError as exc:
            raise ToolError(f"cannot read runtime secret at {secret_file}") from exc
        source = "the runtime secret"

    if len(token_bytes) > MAX_TOKEN_BYTES:
        raise ToolError(f"token from {source} is unexpectedly large")

    try:
        token = token_bytes.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ToolError(f"token from {source} is not valid UTF-8") from exc

    if len(token) < 16 or any(character.isspace() for character in token):
        raise ToolError(f"token from {source} is not in the expected format")
    return token


def websocket_url(address: str, port: int, path: str) -> str:
    host = f"[{address}]" if ":" in address else address
    return f"ws://{host}:{port}{path}"


def connect(address: str, port: int, path: str, token: str) -> websocket.WebSocket:
    try:
        return websocket.create_connection(
            websocket_url(address, port, path),
            header=[f"Authorization: Bearer {token}"],
            timeout=10.0,
            http_no_proxy=["*"],
            suppress_origin=True,
        )
    except websocket.WebSocketBadStatusException as exc:
        if exc.status_code in (401, 403):
            raise ToolError("Remote Phone authentication failed") from exc
        raise ToolError(
            f"Remote Phone rejected the WebSocket upgrade (HTTP {exc.status_code})"
        ) from exc
    except (OSError, websocket.WebSocketException) as exc:
        raise ToolError(
            "cannot connect to the Remote Phone WebSocket endpoint; confirm the app "
            "server is running on the tailnet"
        ) from exc


def close_frame_error(data: bytes) -> ToolError:
    code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else None
    if code in REMOTE_CLOSE_ERRORS:
        return ToolError(f"Remote Phone {REMOTE_CLOSE_ERRORS[code]} (close code {code})")
    if code is not None:
        return ToolError(f"Remote Phone closed the connection (close code {code})")
    return ToolError("Remote Phone closed the connection without a status code")


def receive_frame(ws: websocket.WebSocket) -> tuple[str, bytes | dict]:
    try:
        opcode, frame = ws.recv_data_frame(control_frame=True)
    except websocket.WebSocketTimeoutException:
        raise
    except (OSError, websocket.WebSocketException) as exc:
        raise ToolError("Remote Phone connection failed while receiving data") from exc

    if opcode == websocket.ABNF.OPCODE_CLOSE:
        raise close_frame_error(frame.data)
    if opcode == websocket.ABNF.OPCODE_BINARY:
        return "binary", bytes(frame.data)
    if opcode != websocket.ABNF.OPCODE_TEXT:
        return "control", b""

    try:
        raw_text = (
            frame.data.decode("utf-8")
            if isinstance(frame.data, bytes)
            else str(frame.data)
        )
        event = json.loads(raw_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError("Remote Phone sent an invalid JSON event") from exc
    if not isinstance(event, dict):
        raise ToolError("Remote Phone sent an unexpected JSON event")
    if event.get("event") == "error":
        raise ToolError("Remote Phone reported a capability error")
    return "text", event


def wait_for_ready(ws: websocket.WebSocket) -> dict:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        ws.settimeout(max(0.1, deadline - time.monotonic()))
        try:
            kind, payload = receive_frame(ws)
        except websocket.WebSocketTimeoutException:
            continue
        if kind == "binary":
            raise ToolError("Remote Phone sent audio before its ready event")
        if kind == "text" and payload.get("event") == "ready":
            return payload
    raise ToolError("timed out waiting for the Remote Phone ready event")


def microphone_state(payload: dict) -> str:
    containers = [payload]
    for key in ("capabilities", "enabled", "features"):
        value = payload.get(key)
        if isinstance(value, dict):
            containers.append(value)

    for container in containers:
        value = container.get("microphone")
        if isinstance(value, bool):
            return "enabled" if value else "disabled"
        if isinstance(value, dict):
            enabled = value.get("enabled")
            if isinstance(enabled, bool):
                return "enabled" if enabled else "disabled"
            return "reported"
        if value is not None:
            return str(value)
    return "not reported"


def authenticated_capability_check(args: argparse.Namespace, address: str) -> None:
    token = read_token(args.secret_file, args.token_stdin)
    ws = connect(address, args.port, "/capabilities", token)
    del token
    try:
        ws.settimeout(10.0)
        kind, payload = receive_frame(ws)
        if kind != "text":
            raise ToolError("Remote Phone returned an unexpected capabilities response")
    finally:
        ws.close(timeout=1)

    print(f"Remote Phone: reachable at {address}:{args.port}")
    print(f"Microphone capability: {microphone_state(payload)}")
    print("Audio capture: not started")


def capture_audio(args: argparse.Namespace, address: str) -> bytes:
    token = read_token(args.secret_file, args.token_stdin)
    path = f"/microphone/stream?sampleRate={SAMPLE_RATE}&chunkMs={CHUNK_MS}"
    ws = connect(address, args.port, path, token)
    del token
    try:
        ready = wait_for_ready(ws)
        try:
            actual_rate = int(ready.get("sampleRate"))
            actual_channels = int(ready.get("channels"))
        except (TypeError, ValueError) as exc:
            raise ToolError("Remote Phone ready event omitted its audio format") from exc
        encoding = ready.get("encoding")
        if actual_rate != SAMPLE_RATE or actual_channels != CHANNELS:
            raise ToolError(
                "Remote Phone returned an unsupported audio format "
                f"({actual_rate} Hz, {actual_channels} channels)"
            )
        if encoding not in (None, "pcm_s16le"):
            raise ToolError(f"Remote Phone returned unsupported audio encoding {encoding!r}")

        audio = bytearray()
        deadline = time.monotonic() + args.duration
        byte_limit = int(args.duration * SAMPLE_RATE * SAMPLE_WIDTH) + (
            SAMPLE_RATE * SAMPLE_WIDTH
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ws.settimeout(max(0.05, min(1.0, remaining)))
            try:
                kind, payload = receive_frame(ws)
            except websocket.WebSocketTimeoutException:
                continue
            if kind == "text":
                continue
            if kind != "binary":
                continue
            if len(payload) % SAMPLE_WIDTH != 0:
                raise ToolError("Remote Phone sent a misaligned PCM audio chunk")
            if len(audio) + len(payload) > byte_limit:
                raise ToolError("Remote Phone exceeded the bounded audio buffer")
            audio.extend(payload)
    finally:
        ws.close(timeout=1)

    if not audio:
        raise ToolError("Remote Phone produced no microphone audio")
    return bytes(audio)


def secure_temp_parent() -> str | None:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        return None
    try:
        metadata = os.stat(runtime_dir)
    except OSError:
        return None
    if (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and stat.S_IMODE(metadata.st_mode) & 0o077 == 0
    ):
        return runtime_dir
    return None


def write_wav(path: Path, audio: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as raw_output:
        with wave.open(raw_output, "wb") as output:
            output.setnchannels(CHANNELS)
            output.setsampwidth(SAMPLE_WIDTH)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(audio)


def transcribe(wav_path: Path) -> str:
    whisper_cli = os.environ.get("REMOTE_PHONE_WHISPER_CLI", "whisper-cli")
    model = os.environ.get("REMOTE_PHONE_WHISPER_MODEL")
    if not model:
        raise ToolError("local Whisper model path is not configured")
    if not os.path.isfile(model):
        raise ToolError("local Whisper model is unavailable")

    try:
        result = subprocess.run(
            [
                whisper_cli,
                "--model",
                model,
                "--file",
                str(wav_path),
                "--language",
                "auto",
                "--no-timestamps",
                "--no-prints",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError("local Whisper transcription could not be completed") from exc
    if result.returncode != 0:
        raise ToolError("local Whisper transcription failed")
    return normalize_transcript(result.stdout)


def normalize_transcript(value: str) -> str:
    lines = [
        line.strip()
        for line in value.splitlines()
        if line.strip() and line.strip().upper() != "[BLANK_AUDIO]"
    ]
    return "\n".join(lines)


def doctor(args: argparse.Namespace, address: str) -> None:
    if not args.token_stdin:
        validate_secret_file(args.secret_file)
    model = os.environ.get("REMOTE_PHONE_WHISPER_MODEL")
    whisper_cli = os.environ.get("REMOTE_PHONE_WHISPER_CLI", "whisper-cli")
    if not model or not os.path.isfile(model):
        raise ToolError("local Whisper model is unavailable")
    if not os.path.isfile(whisper_cli) or not os.access(whisper_cli, os.X_OK):
        raise ToolError("local whisper-cli executable is unavailable")

    print(f"Tailnet resolution: {args.host} -> {address}")
    print(
        "Token source: standard input"
        if args.token_stdin
        else "Token source: private SOPS runtime file"
    )
    print("Local transcription backend: ready")
    print("Phone connection: not attempted")
    print("Audio capture: not started")


def run_transcription(args: argparse.Namespace, address: str) -> None:
    audio = capture_audio(args, address)
    with tempfile.TemporaryDirectory(
        prefix="remote-phone-mic-",
        dir=secure_temp_parent(),
    ) as temp_dir:
        os.chmod(temp_dir, 0o700)
        wav_path = Path(temp_dir) / "capture.wav"
        write_wav(wav_path, audio)
        del audio
        transcript = transcribe(wav_path)

    print("Transcript:")
    print(transcript if transcript else "(no speech detected)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "The bearer token is accepted only from the private SOPS runtime file "
            "or standard input. Audio is held in a mode-0700 temporary directory "
            "and deleted after local transcription."
        ),
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="tailnet hostname (default: pixel-10)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="WebSocket port (default: 8080)")
    parser.add_argument(
        "--secret-file",
        type=Path,
        default=Path(os.environ.get("REMOTE_PHONE_TOKEN_FILE", DEFAULT_SECRET_FILE)),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--token-stdin",
        action="store_true",
        help="read the bearer token from standard input instead of SOPS",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "doctor",
        help="validate local prerequisites without connecting to the phone",
    )
    commands.add_parser(
        "check",
        help="query authenticated capabilities without starting audio capture",
    )
    transcribe_parser = commands.add_parser(
        "transcribe",
        help="capture a bounded microphone clip and transcribe it locally",
    )
    transcribe_parser.add_argument(
        "--duration",
        required=True,
        type=bounded_duration,
        metavar="SECONDS",
        help=f"explicit capture duration, greater than 0 and at most {MAX_DURATION_SECONDS:g}",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise ToolError("port must be between 1 and 65535")
    address = resolve_tailnet_address(args.host, args.port)

    if args.command == "doctor":
        doctor(args, address)
    elif args.command == "check":
        authenticated_capability_check(args, address)
    else:
        run_transcription(args, address)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ToolError as error:
        print(f"remote-phone-mic: {error}", file=sys.stderr)
        raise SystemExit(1) from None
