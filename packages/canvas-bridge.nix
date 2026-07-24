{
  lib,
  poppler-utils,
  python3,
  symlinkJoin,
  writeShellApplication,
}:

let
  canvasBridge = writeShellApplication {
    name = "canvas-bridge";
    runtimeInputs = [
      poppler-utils
      python3
    ];
    text = ''
      exec python3 ${../scripts/canvas-bridge.py} "$@"
    '';
  };

  canvasBridgeMcp = writeShellApplication {
    name = "canvas-bridge-mcp";
    text = ''
      exec ${canvasBridge}/bin/canvas-bridge mcp "$@"
    '';
  };
in
symlinkJoin {
  name = "canvas-bridge-0.1.0";
  paths = [
    canvasBridge
    canvasBridgeMcp
  ];

  meta = {
    description = "Read-only UMD Canvas course mirror and Codex MCP connector";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "canvas-bridge";
  };
}
