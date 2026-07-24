{ config, lib, pkgs, ... }:

let
  inherit (lib) mkEnableOption mkIf mkOption types;
  cfg = config.homelab.canvasBridge;
  homelab = config.homelab;
  package = pkgs.callPackage ../../packages/canvas-bridge.nix { };
  stateDir = "${homelab.paths.stateRoot}/canvas-bridge";
in
{
  options.homelab.canvasBridge = {
    enable = mkEnableOption "read-only UMD Canvas course mirror and Codex connector";

    port = mkOption {
      type = types.port;
      default = 8793;
      description = "Loopback port for the private Canvas bridge web interface.";
    };

    syncInterval = mkOption {
      type = types.ints.positive;
      default = 900;
      description = "Seconds between automatic Canvas synchronization attempts.";
    };
  };

  config = mkIf cfg.enable {
    environment.systemPackages = [ package ];

    systemd.tmpfiles.rules = [
      "d ${stateDir} 0700 rishabh users - -"
      "d ${stateDir}/files 0700 rishabh users - -"
    ];

    systemd.services.canvas-bridge = {
      description = "Read-only UMD Canvas course mirror";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];

      environment = {
        CANVAS_BRIDGE_STATE_DIR = stateDir;
        CANVAS_BRIDGE_HOST = "127.0.0.1";
        CANVAS_BRIDGE_PORT = toString cfg.port;
        CANVAS_BRIDGE_PUBLIC_URL = "https://canvas.${homelab.internalDomain}";
        CANVAS_BRIDGE_CANVAS_URL = "https://umd.instructure.com";
        CANVAS_BRIDGE_SYNC_INTERVAL = toString cfg.syncInterval;
        PYTHONDONTWRITEBYTECODE = "1";
      };

      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        ExecStart = "${package}/bin/canvas-bridge serve";
        Restart = "on-failure";
        RestartSec = "5s";
        UMask = "0077";

        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateTmp = true;
        ProtectClock = true;
        ProtectControlGroups = true;
        ProtectHome = true;
        ProtectHostname = true;
        ProtectKernelLogs = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        ReadWritePaths = [ stateDir ];
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

    homelab.routes.canvas = {
      enable = true;
      host = "canvas";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private read-only UMD Canvas course mirror";
    };

    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.canvasBridge.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
