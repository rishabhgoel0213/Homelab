{
  fetchurl,
  lib,
  makeWrapper,
  python3,
  secretFile ? "/run/secrets/remote-phone-token",
  stdenvNoCC,
  whisper-cpp,
}:

let
  pythonEnv = python3.withPackages (ps: [ ps.websocket-client ]);
  whisperModel = fetchurl {
    name = "ggml-base.bin";
    url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/80da2d8bfee42b0e836fc3a9890373e5defc00a6/ggml-base.bin?download=true";
    hash = "sha256-YO1bw90U7qhWST0zQ0m0BXgt3K8AKNS130CINF+6Lv4=";
  };
in
stdenvNoCC.mkDerivation {
  pname = "remote-phone-mic";
  version = "0.1.0";

  src = ../scripts/remote-phone-mic.py;
  dontUnpack = true;
  nativeBuildInputs = [ makeWrapper ];

  doCheck = true;
  checkPhase = ''
    runHook preCheck

    ${pythonEnv}/bin/python -m py_compile "$src"
    REMOTE_PHONE_SCRIPT="$src" ${pythonEnv}/bin/python ${../tests/test-remote-phone-mic.py}

    runHook postCheck
  '';

  installPhase = ''
    runHook preInstall

    install -Dm0555 "$src" "$out/libexec/remote-phone-mic.py"
    makeWrapper ${pythonEnv}/bin/python "$out/bin/remote-phone-mic" \
      --add-flags "$out/libexec/remote-phone-mic.py" \
      --set REMOTE_PHONE_TOKEN_FILE ${lib.escapeShellArg secretFile} \
      --set REMOTE_PHONE_WHISPER_CLI ${lib.escapeShellArg "${whisper-cpp}/bin/whisper-cli"} \
      --set REMOTE_PHONE_WHISPER_MODEL ${lib.escapeShellArg whisperModel}

    runHook postInstall
  '';

  meta = {
    description = "Bounded Remote Phone microphone capture and local transcription tool";
    license = lib.licenses.mit;
    mainProgram = "remote-phone-mic";
    platforms = lib.platforms.linux;
  };
}
