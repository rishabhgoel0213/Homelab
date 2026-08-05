{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.agentSites;
  homelab = config.homelab;
  stateRoot = homelab.paths.agentStateRoot;
  workRoot = homelab.paths.agentWorkRoot;
  python = pkgs.python3.withPackages (ps: [ ps.aiohttp ]);
in
{
  options.homelab.agentSites = {
    enable = lib.mkEnableOption "short-lived internal sites backed by managed agent tasks";

    port = lib.mkOption {
      type = lib.types.port;
      default = 7780;
      description = "Loopback port used by the temporary agent-site gateway.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.agent-site-gateway = {
      description = "Temporary internal site gateway for managed agent tasks";
      wantedBy = [ "multi-user.target" ];
      after = [ "systemd-tmpfiles-setup.service" ];
      environment = {
        AGENT_SITE_REGISTRY = "${stateRoot}/sites.json";
        AGENT_SITE_DOMAIN = homelab.internalDomain;
        AGENT_SITE_GATEWAY_PORT = toString cfg.port;
        AGENT_WORK_ROOT = workRoot;
        PYTHONDONTWRITEBYTECODE = "1";
      };
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        ExecStart = "${python}/bin/python3 ${../../scripts/agent-site-gateway.py}";
        Restart = "on-failure";
        RestartSec = "3s";
        UMask = "0077";

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
        ReadOnlyPaths = [ workRoot ];
        ReadWritePaths = [ stateRoot ];
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
        ];
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
      };
    };

    systemd.services.caddy = {
      wants = [ "agent-site-gateway.service" ];
      after = [ "agent-site-gateway.service" ];
    };

    systemd.services.agent-site-gc = {
      description = "Prune expired and orphaned temporary agent sites";
      after = [ "systemd-tmpfiles-setup.service" ];
      serviceConfig = {
        Type = "oneshot";
        User = "rishabh";
        Group = "users";
        UMask = "0077";
        ExecStart = "/run/current-system/sw/bin/agent site prune --quiet";
        NoNewPrivileges = true;
        PrivateDevices = true;
        ProtectHome = true;
        ProtectSystem = "strict";
        ReadOnlyPaths = [ workRoot ];
        ReadWritePaths = [ stateRoot ];
        RestrictAddressFamilies = [ "AF_UNIX" ];
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
      };
    };

    systemd.timers.agent-site-gc = {
      description = "Periodically prune temporary agent sites";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "10m";
        OnUnitInactiveSec = "15m";
        Persistent = true;
        Unit = "agent-site-gc.service";
      };
    };

    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.agentSites.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
