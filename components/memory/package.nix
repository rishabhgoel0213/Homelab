{
  lib,
  python3,
  runCommand,
  tzdata,
  writeShellApplication,
  url ? "",
  t3Url ? "",
  stateDirectory ? "/srv/state/memory",
  t3Db ? "/srv/state/t3code/userdata/statev2.sqlite",
  syncTargets ? "/srv/state/codex/AGENTS.md:/srv/state/claude/CLAUDE.md:/srv/state/antigravity/config/AGENTS.md",
  timeZone ? "America/New_York",
}:

let
  web = ./web;
  memoryBin = writeShellApplication {
    name = "memory";
    runtimeInputs = [ python3 ];
    text = ''
      export PYTHONTZPATH=${tzdata}/share/zoneinfo
      export PYTHONDONTWRITEBYTECODE=1
      export MEMORY_STATE=''${MEMORY_STATE:-${stateDirectory}}
      export MEMORY_TIMEZONE=''${MEMORY_TIMEZONE:-${timeZone}}
      export MEMORY_URL=''${MEMORY_URL:-${url}}
      export MEMORY_WEB=${web}
      export MEMORY_T3_DB=''${MEMORY_T3_DB:-${t3Db}}
      export MEMORY_SYNC_TARGETS=''${MEMORY_SYNC_TARGETS:-${syncTargets}}
      export T3_HISTORY_SCRIPT=${./bin/t3-history.py}
      exec python3 ${./bin/memory.py} "$@"
    '';
  };
  t3HistoryBin = writeShellApplication {
    name = "t3-history";
    runtimeInputs = [ python3 ];
    text = ''
      export PYTHONTZPATH=${tzdata}/share/zoneinfo
      export PYTHONDONTWRITEBYTECODE=1
      export T3_HISTORY_DB=''${T3_HISTORY_DB:-${t3Db}}
      export T3_HISTORY_URL=''${T3_HISTORY_URL:-${t3Url}}
      export T3_HISTORY_TIMEZONE=''${T3_HISTORY_TIMEZONE:-${timeZone}}
      exec python3 ${./bin/t3-history.py} "$@"
    '';
  };
in
runCommand "homelab-memory"
  {
    meta = {
      description = "Curated agent memory CLI, web UI, consolidator, and read-only T3 chat history tool";
      license = lib.licenses.mit;
      platforms = lib.platforms.linux;
      mainProgram = "memory";
    };
  }
  ''
    mkdir -p "$out/bin"
    ln -s ${memoryBin}/bin/memory "$out/bin/memory"
    ln -s ${t3HistoryBin}/bin/t3-history "$out/bin/t3-history"
  ''
