{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.zenSpaceRouter;
  python = pkgs.python3.withPackages (p: [
    p.httpx
    p.h2
  ]);
in
{
  options.homelab.zenSpaceRouter = {
    enable = lib.mkEnableOption "Jev-backed Zen Browser space routing service";
    port = lib.mkOption {
      type = lib.types.port;
      default = 8129;
      description = "Loopback port used by the Zen Space Router service.";
    };
    model = lib.mkOption {
      type = lib.types.str;
      default = "jev-latest";
      description = "TypeSafe AI Jev model identifier.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.zen-space-router = {
      description = "Jev-backed Zen Browser Space Router";
      wantedBy = [ "multi-user.target" ];
      after = [
        "network-online.target"
        "sops-nix.service"
      ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        ExecStart = "${python}/bin/python ${./server.py} --host 127.0.0.1 --port ${toString cfg.port} --api-key-file %d/jev-api-key --model ${lib.escapeShellArg cfg.model}";
        LoadCredential = "jev-api-key:${config.sops.secrets."jev-api-key".path}";
        DynamicUser = true;
        UMask = "0077";
        Restart = "always";
        RestartSec = 3;
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
      };
    };

    homelab.routes.zen-router = {
      enable = true;
      host = "zen-router";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private Jev-backed Zen Browser space routing API";
    };

    assertions = [
      {
        assertion = config.homelab.secrets.enable;
        message = "homelab.zenSpaceRouter.enable requires homelab.secrets.enable for jev-api-key.";
      }
      {
        assertion = config.homelab.acme.enable;
        message = "homelab.zenSpaceRouter.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
