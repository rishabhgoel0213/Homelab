{
  lib,
  poppler-utils,
  python3,
  writeShellApplication,
}:

writeShellApplication {
  name = "canvas-bridge";
  runtimeInputs = [
    poppler-utils
    python3
  ];
  text = ''
    exec python3 ${./bin/canvas-bridge.py} "$@"
  '';
  meta = {
    description = "Read-only UMD Canvas course mirror and CLI";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "canvas-bridge";
  };
}
