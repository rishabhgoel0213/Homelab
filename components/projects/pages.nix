{ config, lib, pkgs, ... }:

let
  inherit (config) homelab;
  cfg = homelab.projectPages;
  python = pkgs.python3.withPackages (ps: [ ps.aiohttp ]);
in
{
  options.homelab.projectPages = {
    enable = lib.mkEnableOption "read-only project files through private HTTPS";
    port = lib.mkOption {
      type = lib.types.port;
      default = 8795;
      description = "Loopback port for the project file server.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.project-pages = {
      description = "Private read-only project files";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      environment.PYTHONDONTWRITEBYTECODE = "1";
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        ExecStart = "${python}/bin/python3 ${./bin/project-pages.py} --root ${lib.escapeShellArg homelab.paths.projectsRoot} --port ${toString cfg.port}";
        Restart = "on-failure";
        RestartSec = "5s";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        # Expose only Projects from the user's home, without changing its ACLs.
        ProtectHome = "tmpfs";
        BindReadOnlyPaths = [ homelab.paths.projectsRoot ];
        RestrictAddressFamilies = [ "AF_INET" "AF_UNIX" ];
      };
    };

    homelab.routes.project-pages = {
      host = "projects";
      visibility = "internal";
      description = "Direct project files, read-only, without directory listings";
      caddyConfig = ''
        @outsideTailnet not remote_ip 100.64.0.0/10 fd7a:115c:a1e0::/48
        respond @outsideTailnet "Tailnet access required." 403
        encode zstd gzip
        reverse_proxy http://127.0.0.1:${toString cfg.port}
      '';
    };
  };
}
