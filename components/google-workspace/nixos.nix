{ config, pkgs, ... }:

let
  cfg = config.homelab;
  stateDir = "${cfg.paths.stateRoot}/google-workspace";

  gog = pkgs.writeShellApplication {
    name = "gog";
    runtimeInputs = with pkgs; [
      coreutils
      gawk
    ];
    text = ''
      export GOG_STATE_DIR="''${GOG_STATE_DIR:-${stateDir}}"
      export GOG_REAL_BIN="${pkgs.gogcli}/bin/gog"
      exec ${pkgs.bash}/bin/bash ${./bin/gog-wrapper} "$@"
    '';
  };
in
{
  systemd.tmpfiles.rules = [
    "d ${stateDir} 0700 rishabh users - -"
    "d ${stateDir}/config 0700 rishabh users - -"
  ];

  environment.systemPackages = [
    gog
  ];
}
