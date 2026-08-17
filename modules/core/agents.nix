{
  config,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  stateRoot = cfg.paths.agentStateRoot;
  workRoot = cfg.paths.agentWorkRoot;
  agentTools = pkgs.writeShellApplication {
    name = "agent";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      export AGENT_STATE_ROOT=${stateRoot}
      export AGENT_WORK_ROOT=${workRoot}
      export AGENT_POLICY_ROOT=/etc/agents
      export AGENT_SITE_REGISTRY=${stateRoot}/sites.json
      export AGENT_SITE_DOMAIN=${cfg.internalDomain}
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
    "d ${stateRoot} 0700 rishabh users - -"
    "d ${workRoot} 0700 rishabh users - -"
  ];

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
