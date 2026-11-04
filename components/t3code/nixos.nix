{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  cfg = config.homelab.t3code;
  stateDir = homelab.paths.t3codeState;
  package = pkgs.callPackage ./package.nix { };
in
{
  options.homelab.t3code = {
    enable = lib.mkEnableOption "T3 Code private coding-agent web UI";
    port = lib.mkOption {
      type = lib.types.port;
      default = 3773;
      description = "Loopback port used by the T3 Code server.";
    };
  };
  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ package ];
    systemd.tmpfiles.rules = [ "d ${stateDir} 0700 rishabh users - -" ];
    systemd.services.t3code = {
      description = "Official T3 Code nightly server";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      path = with pkgs; [
        bash
        coreutils
        fd
        findutils
        gh
        git
        gnugrep
        gnused
        jq
        just
        nix
        openssh
        ripgrep
      ];
      environment = {
        CODEX_HOME = homelab.paths.codexHome;
        HOME = homelab.paths.userHome;
        SHELL = "${pkgs.bash}/bin/bash";
        T3CODE_HOME = stateDir;
      };
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        WorkingDirectory = stateDir;
        ExecStart = "${package}/bin/t3 serve --host 127.0.0.1 --port ${toString cfg.port} --base-dir ${stateDir} --no-browser";
        Restart = "on-failure";
        RestartSec = "5s";
        UMask = "0077";
      };
    };
    systemd.services.t3code-auto-update = {
      description = "Update T3 Code to the latest official nightly";
      wants = [ "network-online.target" ];
      after = [
        "network-online.target"
        "pi-auto-update.service"
      ];
      path = with pkgs; [
        bash
        coreutils
        curl
        gawk
        gnugrep
        jq
        nix
        nixos-rebuild
        perl
        sudo
        systemd
        util-linux
      ];
      environment = {
        T3CODE_OPS_ROOT = homelab.paths.opsRoot;
        HOST = config.networking.hostName;
      };
      serviceConfig = {
        Type = "oneshot";
        WorkingDirectory = homelab.paths.opsRoot;
        ExecStart = "${homelab.paths.opsRoot}/components/t3code/bin/auto-update";
      };
    };
    systemd.timers.t3code-auto-update = {
      description = "Daily official T3 Code nightly update";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "*-*-* 06:00:00";
        Persistent = true;
        RandomizedDelaySec = "10m";
        Unit = "t3code-auto-update.service";
      };
    };
    homelab.routes.t3code = {
      enable = true;
      host = "t3code";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private official T3 Code nightly UI";
    };
    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.t3code.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
