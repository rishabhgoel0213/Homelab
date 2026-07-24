{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  remotePhoneMic = pkgs.callPackage ../../packages/remote-phone-mic.nix { };
in
{
  config = lib.mkIf cfg.remotePhone.enable {
    environment.systemPackages = [ remotePhoneMic ];

    assertions = [
      {
        assertion = cfg.secrets.enable;
        message = "homelab.remotePhone.enable requires homelab.secrets.enable for the bearer token.";
      }
    ];
  };
}
