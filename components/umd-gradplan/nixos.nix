{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.homelab.umdGradplan;
  project = "${config.homelab.paths.projectsRoot}/umd-gradplan";
  state = "${config.homelab.paths.stateRoot}/umd-gradplan";
  # Explicit allowlist: no student records, workbook, tests, or private artifacts
  # may enter the world-readable Nix store.
  bundle = builtins.path {
    path = builtins.toPath project;
    name = "umd-gradplan-public-bundle";
    filter =
      path: type:
      let
        relative = lib.removePrefix (project + "/") (toString path);
        parts = lib.splitString "/" relative;
        first = builtins.head parts;
      in
      (
        toString path == project
        || builtins.elem first [
          "src"
          "web"
          "data"
          "sources"
          "schemas"
        ]
      )
      && !(builtins.elem "private" parts)
      && !(builtins.elem "__pycache__" parts)
      && !(lib.hasSuffix ".pyc" relative);
  };
  python = pkgs.python3.withPackages (ps: [
    ps.beautifulsoup4
    ps.requests
    ps.jsonschema
  ]);
  hostname = "plan.${config.homelab.internalDomain}";
in
{
  options.homelab.umdGradplan.enable = lib.mkEnableOption "private UMD graduation planner";
  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [ "d ${state} 0700 rishabh users - -" ];
    systemd.services.umd-gradplan = {
      description = "Private UMD graduation planner";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      environment = {
        PYTHONPATH = "${bundle}/src";
        PYTHONDONTWRITEBYTECODE = "1";
      };
      serviceConfig = {
        User = "rishabh";
        Group = "users";
        ExecStart = "${python}/bin/python3 -m gradplan.webserver --state ${state} --bundle ${bundle} --seed ${project}/data/private/student.json --port 8796 --allowed-host ${hostname}";
        Restart = "on-failure";
        RestartSec = "5s";
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = "tmpfs";
        BindReadOnlyPaths = [ "${project}/data/private/student.json" ];
        ReadWritePaths = [ state ];
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
      };
    };
    systemd.services.umd-gradplan-backup = {
      description = "Consistent daily graduation-planner backup";
      after = [ "umd-gradplan.service" ];
      serviceConfig = {
        Type = "oneshot";
        User = "rishabh";
        Group = "users";
        ExecStart = "${pkgs.python3}/bin/python3 ${./backup.py} ${state}";
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ReadWritePaths = [ state ];
      };
    };
    systemd.timers.umd-gradplan-backup = {
      description = "Daily graduation-planner snapshots";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "daily";
        RandomizedDelaySec = "5m";
        Persistent = true;
      };
    };
    homelab.routes.umd-gradplan = {
      host = "plan";
      visibility = "internal";
      description = "Private UMD graduation planner";
      caddyConfig = ''
        @outsideTailnet not remote_ip 100.64.0.0/10 fd7a:115c:a1e0::/48
        respond @outsideTailnet "Tailnet access required." 403
        encode zstd gzip
        reverse_proxy http://127.0.0.1:8796
      '';
    };
  };
}
