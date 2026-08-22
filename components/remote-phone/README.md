# Remote Phone microphone

`remote-phone-mic` is the server-side client for the Pixel's tailnet-only Remote
Phone microphone endpoint. It captures only for an explicit bounded duration
and transcribes locally with the declaratively pinned multilingual
`whisper.cpp` base model.

The tool refuses non-Tailscale destination addresses, bypasses HTTP proxy
settings so the bearer token stays inside the tailnet connection, never accepts
the token in an argument or URL, and caps every capture at 60 seconds. Captured
audio exists only as a mode-`0600` WAV inside a mode-`0700` temporary directory;
the directory is removed after transcription, including on failure.

## Promote the existing token

From `/srv/ops`, use the existing selective Bitwarden-to-SOPS workflow:

```bash
just bitwarden-promote
```

Choose the Remote Phone item and its token field. Decline the optional terminal
reveal, select `<new key>`, and name the SOPS key:

```text
remote-phone-token
```

The encrypted source remains
`/home/rishabh/.config/homelab/secrets.yaml`. After deployment, sops-nix
materializes only that key at `/run/secrets/remote-phone-token`, owned by
`rishabh` with mode `0400`.

## Validate without recording

After an explicitly approved deployment:

```bash
remote-phone-mic doctor
```

This checks tailnet DNS, private runtime-secret metadata, and the local Whisper
backend. It does not connect to the phone.

Then query authenticated capabilities without opening the microphone:

```bash
remote-phone-mic check
```

The output confirms whether the microphone capability is enabled and explicitly
states that audio capture was not started.

## Capture and transcribe

Every capture requires a duration. For example, this records five seconds,
transcribes locally, prints only the transcript, and deletes the temporary WAV:

```bash
remote-phone-mic transcribe --duration 5
```

Durations greater than 60 seconds are rejected. The fixed endpoint is:

```text
ws://pixel-10:8080/microphone/stream?sampleRate=16000&chunkMs=20
```

The bearer token is sent only in the `Authorization` WebSocket upgrade header.
For one-off recovery use, `--token-stdin` accepts a token from a secure producer;
there is intentionally no token argument or environment-variable mode.

Remote Phone close codes are translated into operator-safe errors for invalid
authentication, disabled capability, invalid configuration, busy or failed
audio resources, and non-tailnet peers. If `pixel-10` does not resolve to a
Tailscale IPv4 or IPv6 address, the tool refuses to send the credential.

## Deploy

Configuration changes do not affect the live host until explicitly approved:

```bash
just check
just switch
```

Do not run `just switch`, `remote-phone-mic check`, or a real transcription
capture merely to validate a configuration-only change.
