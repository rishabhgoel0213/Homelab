{
  lib,
  python3,
  tzdata,
  writeShellApplication,
}:

writeShellApplication {
  name = "codex-scheduler";
  runtimeInputs = [ python3 ];
  text = ''
    export PYTHONTZPATH=${tzdata}/share/zoneinfo
    exec python3 ${./bin/codex-scheduler.py} "$@"
  '';
  meta = {
    description = "Persistent local Codex schedules with stdio MCP management";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "codex-scheduler";
  };
}
