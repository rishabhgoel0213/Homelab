{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  cfg = homelab.tasks;
  stateDirectory = "${homelab.paths.stateRoot}/tasks";
  fqdn = "tasks.${homelab.internalSubdomain}.${homelab.domain}";
  tasks = pkgs.callPackage ./package.nix {
    url = "https://${fqdn}";
    inherit stateDirectory;
    timeZone = config.time.timeZone;
  };
in
{
  options.homelab.tasks = {
    enable = lib.mkEnableOption "private weekly to-do board for people and agents";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8740;
      description = "Loopback port used by the task board web server.";
    };
  };

  config = lib.mkIf cfg.enable {
    # The CLI and MCP server open the same SQLite database directly as rishabh.
    environment.systemPackages = [ tasks ];

    systemd.tmpfiles.rules = [
      "d ${stateDirectory} 0700 rishabh users -"
    ];

    systemd.services.tasks = {
      description = "Weekly to-do board web server";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        WorkingDirectory = stateDirectory;
        ExecStart = "${lib.getExe tasks} serve --host 127.0.0.1 --port ${toString cfg.port}";
        Restart = "on-failure";
        RestartSec = "3s";
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ReadWritePaths = [ stateDirectory ];
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
      };
    };

    homelab.routes.tasks = {
      enable = true;
      host = "tasks";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private weekly to-do board shared with agents";
    };

    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.tasks.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
      {
        assertion = lib.hasPrefix "/srv/state/" stateDirectory;
        message = "Task board state must live under /srv/state.";
      }
    ];
  };
}
