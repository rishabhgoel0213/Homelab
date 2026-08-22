{ config, lib, pkgs, ... }:

let
  cfg = config.homelab;
in
{
  config = lib.mkIf cfg.syncthing.enable {
    services.syncthing = {
      enable = true;
      user = "rishabh";
      group = "users";
      configDir = "${cfg.paths.stateRoot}/syncthing";
      guiAddress = "127.0.0.1:8384";

      # Pair the Mac and manage shared folders from Syncthing's UI. This keeps
      # Nix from deleting device/folder changes made during normal onboarding.
      overrideDevices = false;
      overrideFolders = false;

      # Keep sync traffic private to the tailnet/firewall instead of relying on
      # Syncthing's public discovery or relay network.
      openDefaultPorts = false;
      settings.options = {
        globalAnnounceEnabled = false;
        listenAddresses = [ "tcp://${cfg.tailnetIp}:22000" ];
        localAnnounceEnabled = false;
        relaysEnabled = false;
        urAccepted = -1;
      };
    };

    systemd.services.syncthing = {
      wants = [
        "network-online.target"
        "tailscaled.service"
      ];
      after = [
        "network-online.target"
        "tailscaled.service"
      ];
    };

    environment.systemPackages = with pkgs; [
      syncthing
    ];

    systemd.tmpfiles.rules = [
      "d ${cfg.paths.stateRoot}/syncthing 0700 rishabh users - -"
    ];

    homelab.routes.sync = {
      enable = true;
      host = "sync";
      visibility = "internal";
      upstream = "http://127.0.0.1:8384";
      upstreamHostHeader = "127.0.0.1:8384";
      description = "Syncthing private file sync UI";
    };

    assertions = [
      {
        assertion = cfg.tailnetIp != null;
        message = "homelab.syncthing.enable requires homelab.tailnetIp so sync traffic can bind to Tailscale.";
      }
    ];
  };
}
