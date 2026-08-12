{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (lib)
    mkEnableOption
    mkIf
    mkOption
    types
    ;
  cfg = config.homelab.singlemail;
  homelab = config.homelab;
  package = pkgs.callPackage ../../packages/singlemail.nix { };
in
{
  options.homelab.singlemail = {
    enable = mkEnableOption "private purpose-scoped disposable inbox service";

    port = mkOption {
      type = types.port;
      default = 8794;
      description = "Loopback port for the private Singlemail web gateway.";
    };

    apiUrl = mkOption {
      type = types.str;
      default = "https://singlemail.rishabhgoel0213.workers.dev";
      description = "Cloudflare Worker API URL used by the gateway and CLI.";
    };
  };

  config = mkIf cfg.enable {
    environment.systemPackages = [ package ];

    systemd.services.singlemail = {
      description = "Private Singlemail web gateway";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];

      environment = {
        SINGLEMAIL_API_URL = cfg.apiUrl;
        SINGLEMAIL_HOST = "127.0.0.1";
        SINGLEMAIL_PORT = toString cfg.port;
        SINGLEMAIL_PUBLIC_URL = "https://maildrop.${homelab.internalDomain}";
        PYTHONDONTWRITEBYTECODE = "1";
      };

      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        EnvironmentFile = config.sops.secrets."singlemail.env".path;
        ExecStart = "${package}/bin/singlemail serve";
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

    homelab.routes.maildrop = {
      enable = true;
      host = "maildrop";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private purpose-scoped disposable inbox manager";
    };

    assertions = [
      {
        assertion = homelab.secrets.enable;
        message = "homelab.singlemail.enable requires homelab.secrets.enable for its Worker API token.";
      }
      {
        assertion = homelab.acme.enable;
        message = "homelab.singlemail.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
