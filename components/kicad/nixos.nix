{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  kicadState = "${cfg.paths.stateRoot}/kicad";
  projectRoot = "/home/rishabh/Documents/KiCad";
  kicadPort = 6098;
in
{
  config = lib.mkIf cfg.kicad.enable {
    environment.systemPackages = [ pkgs.kicad ];

    systemd.tmpfiles.rules = [
      "d ${kicadState} 0700 rishabh users - -"
      "d ${kicadState}/home 0700 rishabh users - -"
      "d ${kicadState}/runtime 0700 rishabh users - -"
      "d ${kicadState}/config 0700 rishabh users - -"
      "d ${kicadState}/cache 0700 rishabh users - -"
      "d ${kicadState}/data 0700 rishabh users - -"
      "d ${kicadState}/log 0700 rishabh users - -"
      "d ${projectRoot} 0750 rishabh users - -"
    ];

    systemd.services.kicad-web = {
      description = "KiCad private Xpra application service";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      environment = {
        HOME = "${kicadState}/home";
        XDG_RUNTIME_DIR = "${kicadState}/runtime";
        XDG_CONFIG_HOME = "${kicadState}/config";
        XDG_CACHE_HOME = "${kicadState}/cache";
        XDG_DATA_HOME = "${kicadState}/data";
        GDK_BACKEND = "x11";
        QT_QPA_PLATFORM = "xcb";
        NO_AT_BRIDGE = "1";
      };
      path = [
        pkgs.dbus
        pkgs.kicad
        pkgs.xauth
        pkgs.xpra
      ];
      serviceConfig = {
        User = "rishabh";
        Group = "users";
        ExecStart = lib.concatStringsSep " " [
          "${pkgs.dbus}/bin/dbus-run-session"
          "--"
          "${pkgs.xpra}/bin/xpra"
          "start"
          ":88"
          "--daemon=no"
          "--use-display=no"
          "--resize-display=1920x1080"
          "--bind=none"
          "--bind-tcp=127.0.0.1:${toString kicadPort}"
          "--tcp-auth=none"
          "--html=${pkgs.xpra-html5}/share/xpra/www"
          "--mdns=no"
          "--dbus=no"
          "--source="
          "--systemd-run=no"
          "--pulseaudio=no"
          "--speaker=off"
          "--microphone=off"
          "--webcam=no"
          "--printing=no"
          "--file-transfer=no"
          "--open-files=no"
          "--open-url=no"
          "--notifications=no"
          "--clipboard=yes"
          "--shell=no"
          "--control=no"
          "--start-new-commands=no"
          "--terminate-children=yes"
          "--exit-with-children=yes"
          "--start-child=${pkgs.kicad}/bin/kicad"
          "--chdir=${projectRoot}"
          "--session-name=KiCad"
          "--log-dir=${kicadState}/log"
        ];
        Restart = "on-failure";
        RestartSec = "5s";
        WorkingDirectory = projectRoot;
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        ReadWritePaths = [
          kicadState
          projectRoot
        ];
      };
    };

    homelab.routes.cad = {
      enable = true;
      host = "cad";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString kicadPort}";
      description = "KiCad private Xpra application service";
      extraConfig = ''
        header {
          X-Robots-Tag "noindex, nofollow"
        }
      '';
    };

    assertions = [
      {
        assertion = cfg.acme.enable;
        message = "homelab.kicad.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
