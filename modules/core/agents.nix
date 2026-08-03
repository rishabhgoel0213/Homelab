{
  config,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  cockpit = cfg.paths.agentCockpit;
  stateRoot = cfg.paths.agentStateRoot;
  workRoot = cfg.paths.agentWorkRoot;
  codexHome = cfg.paths.codexHome;
  agentTools = pkgs.writeShellApplication {
    name = "agent";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      export AGENT_STATE_ROOT=${stateRoot}
      export AGENT_WORK_ROOT=${workRoot}
      export CODEX_HOME=${codexHome}
      exec python3 ${../../scripts/agent.py} "$@"
    '';
  };
  withNix = pkgs.writeShellApplication {
    name = "with-nix";
    runtimeInputs = [ pkgs.nix ];
    text = ''
      export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-/tmp/codex-nix-cache}"
      export NIX_CONFIG="''${NIX_CONFIG:-experimental-features = nix-command flakes}"
      exec nix "$@"
    '';
  };
in
{
  environment.systemPackages = [
    agentTools
    withNix
  ];

  environment.etc = {
    "agents/AGENTS.md".source = ../../agents/AGENTS.md;
    "agents/ENVIRONMENT.md".source = ../../agents/ENVIRONMENT.md;
    "agents/MEMORY.md".source = ../../agents/MEMORY.md;
    "agents/README.md".source = ../../agents/README.md;
  };

  systemd.tmpfiles.rules = [
    "d ${cockpit} 0555 rishabh users - -"
    "L+ ${cockpit}/AGENTS.md - - - - /etc/agents/AGENTS.md"
    "L+ ${cockpit}/ENVIRONMENT.md - - - - /etc/agents/ENVIRONMENT.md"
    "L+ ${cockpit}/MEMORY.md - - - - /etc/agents/MEMORY.md"
    "L+ ${cockpit}/README.md - - - - /etc/agents/README.md"
    "L+ ${cockpit}/history - - - - ${stateRoot}"
    "d ${stateRoot} 0700 rishabh users - -"
    "d ${workRoot} 0700 rishabh users - -"
  ];

  systemd.services.agent-conversation-index = {
    description = "Build the metadata-only agent conversation index";
    after = [ "systemd-tmpfiles-setup.service" ];
    serviceConfig = {
      Type = "oneshot";
      User = "rishabh";
      Group = "users";
      UMask = "0077";
      ExecStart = "${agentTools}/bin/agent index --quiet";
      NoNewPrivileges = true;
      PrivateDevices = true;
      ProtectClock = true;
      ProtectControlGroups = true;
      ProtectHome = true;
      ProtectHostname = true;
      ProtectKernelLogs = true;
      ProtectKernelModules = true;
      ProtectKernelTunables = true;
      ProtectSystem = "strict";
      ReadOnlyPaths = [ codexHome ];
      ReadWritePaths = [ stateRoot ];
      RestrictAddressFamilies = [ "AF_UNIX" ];
      RestrictNamespaces = true;
      RestrictRealtime = true;
      RestrictSUIDSGID = true;
      LockPersonality = true;
      MemoryDenyWriteExecute = true;
    };
  };

  systemd.paths.agent-conversation-index = {
    description = "Refresh the agent conversation index when Codex metadata changes";
    wantedBy = [ "paths.target" ];
    pathConfig = {
      PathChanged = "${codexHome}/session_index.jsonl";
      Unit = "agent-conversation-index.service";
    };
  };

  systemd.timers.agent-conversation-index = {
    description = "Periodically refresh the agent conversation index";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "5m";
      OnUnitActiveSec = "15m";
      Persistent = true;
      Unit = "agent-conversation-index.service";
    };
  };

  systemd.services.agent-work-gc = {
    description = "Remove expired manifest-managed agent work directories";
    after = [ "systemd-tmpfiles-setup.service" ];
    serviceConfig = {
      Type = "oneshot";
      User = "rishabh";
      Group = "users";
      UMask = "0077";
      ExecStart = "${agentTools}/bin/agent gc --apply --quiet";
      NoNewPrivileges = true;
      PrivateDevices = true;
      ProtectClock = true;
      ProtectControlGroups = true;
      ProtectHome = true;
      ProtectHostname = true;
      ProtectKernelLogs = true;
      ProtectKernelModules = true;
      ProtectKernelTunables = true;
      ProtectSystem = "strict";
      ReadWritePaths = [ workRoot ];
      RestrictAddressFamilies = [ "AF_UNIX" ];
      RestrictNamespaces = true;
      RestrictRealtime = true;
      RestrictSUIDSGID = true;
      LockPersonality = true;
      MemoryDenyWriteExecute = true;
    };
  };

  systemd.timers.agent-work-gc = {
    description = "Daily cleanup of expired agent work directories";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "30m";
      Unit = "agent-work-gc.service";
    };
  };
}
