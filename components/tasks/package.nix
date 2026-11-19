{
  lib,
  python3,
  tzdata,
  writeShellApplication,
  url ? "",
  stateDirectory ? "/srv/state/tasks",
  timeZone ? "America/New_York",
}:

let
  web = ./web;
in
writeShellApplication {
  name = "tasks";
  runtimeInputs = [ python3 ];
  text = ''
    export PYTHONTZPATH=${tzdata}/share/zoneinfo
    export PYTHONDONTWRITEBYTECODE=1
    export TASKS_STATE=''${TASKS_STATE:-${stateDirectory}}
    export TASKS_TIMEZONE=''${TASKS_TIMEZONE:-${timeZone}}
    export TASKS_URL=''${TASKS_URL:-${url}}
    export TASKS_WEB=${web}
    exec python3 ${./bin/tasks.py} "$@"
  '';
  meta = {
    description = "Weekly to-do board with a tailnet web page, CLI and stdio MCP tools";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "tasks";
  };
}
