{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  cfg = homelab.memory;
  stateDirectory = "${homelab.paths.stateRoot}/memory";
  fqdn = "memory.${homelab.internalSubdomain}.${homelab.domain}";
  t3Fqdn = "t3code.${homelab.internalSubdomain}.${homelab.domain}";
  syncTargets = lib.concatStringsSep ":" [
    "${homelab.paths.codexHome}/AGENTS.md"
    "${homelab.paths.stateRoot}/claude/CLAUDE.md"
    "${homelab.paths.stateRoot}/antigravity/config/AGENTS.md"
  ];
  agyPkg = pkgs.callPackage ../antigravity/package.nix { };
  memory = pkgs.callPackage ./package.nix {
    url = "https://${fqdn}";
    t3Url = "https://${t3Fqdn}";
    inherit stateDirectory syncTargets;
    t3Db = "${homelab.paths.t3codeState}/userdata/statev2.sqlite";
    timeZone = config.time.timeZone;
  };
  runuser = "${pkgs.util-linux}/bin/runuser -u rishabh --";
in
{
  options.homelab.memory = {
    enable = lib.mkEnableOption "curated cross-agent user memory and T3 chat history search";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8742;
      description = "Loopback port used by the agent memory web server.";
    };

    consolidateBackend = lib.mkOption {
      type = lib.types.enum [
        "agy"
        "claude"
        "codex"
      ];
      default = "agy";
      description = "Headless agent CLI used for nightly memory consolidation.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ memory ];

    systemd.tmpfiles.rules = [
      "d ${stateDirectory} 0700 rishabh users -"
    ];

    # Re-inject the rendered User Memory block into all server agent instruction
    # files immediately after activation refreshes the base AGENTS.md / CLAUDE.md.
    system.activationScripts.memorySync = {
      deps = [
        "users"
        "codexConfig"
        "claudeConfig"
        "antigravityConfig"
      ];
      text = ''
        install -d -m 0700 -o rishabh -g users ${lib.escapeShellArg stateDirectory}
        ${runuser} ${memory}/bin/memory sync >/dev/null
      '';
    };

    systemd.services.memory = {
      description = "Curated agent memory web UI server";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      path = [
        agyPkg
        pkgs.bash
        pkgs.coreutils
      ];
      environment = {
        HOME = homelab.paths.userHome;
        CODEX_HOME = homelab.paths.codexHome;
        CLAUDE_CONFIG_DIR = "${homelab.paths.stateRoot}/claude";
        MEMORY_CONSOLIDATE_BACKEND = cfg.consolidateBackend;
      };
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        WorkingDirectory = stateDirectory;
        ExecStart = "${memory}/bin/memory serve --host 127.0.0.1 --port ${toString cfg.port}";
        Restart = "on-failure";
        RestartSec = "3s";
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        ReadWritePaths = [
          stateDirectory
          homelab.paths.codexHome
          "${homelab.paths.stateRoot}/claude"
          "${homelab.paths.stateRoot}/antigravity"
        ];
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
      };
    };

    systemd.services.memory-consolidate = {
      description = "Consolidate durable user memories from recent T3 Code chats";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      path = [
        agyPkg
        pkgs.bash
        pkgs.coreutils
      ];
      environment = {
        HOME = homelab.paths.userHome;
        CODEX_HOME = homelab.paths.codexHome;
        CLAUDE_CONFIG_DIR = "${homelab.paths.stateRoot}/claude";
        MEMORY_CONSOLIDATE_BACKEND = cfg.consolidateBackend;
      };
      serviceConfig = {
        Type = "oneshot";
        User = "rishabh";
        Group = "users";
        WorkingDirectory = stateDirectory;
        ExecStart = "${memory}/bin/memory consolidate --backend ${cfg.consolidateBackend}";
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        ReadWritePaths = [
          stateDirectory
          homelab.paths.codexHome
          "${homelab.paths.stateRoot}/claude"
          "${homelab.paths.stateRoot}/antigravity"
        ];
      };
    };

    systemd.timers.memory-consolidate = {
      description = "Nightly consolidation of durable user memories from T3 chats";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "*-*-* 03:30:00";
        Persistent = true;
        RandomizedDelaySec = "5m";
        Unit = "memory-consolidate.service";
      };
    };

    homelab.routes.memory = {
      enable = true;
      host = "memory";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private curated agent memory dashboard";
    };

    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.memory.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
      {
        assertion = lib.hasPrefix "/srv/state/" stateDirectory;
        message = "Memory state must live under /srv/state.";
      }
    ];
  };
}
