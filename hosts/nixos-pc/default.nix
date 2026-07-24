{ config, lib, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix

    ../../modules/homelab/options.nix
    ../../modules/homelab/ingress.nix

    ../../modules/core/base.nix
    ../../modules/core/codex.nix
    ../../modules/core/computer-use.nix
    ../../modules/core/containers.nix
    ../../modules/core/filesystem.nix
    ../../modules/core/gpu.nix
    ../../modules/core/remote-phone.nix
    ../../modules/core/secrets.nix
    ../../modules/core/dns.nix
    ../../modules/core/cloudflare.nix
    ../../modules/core/tailscale-api.nix
    ../../modules/core/vscode-remote.nix

    ../../modules/services/vaultwarden.nix
    ../../modules/services/backrest.nix
    ../../modules/services/canvas-bridge.nix
    ../../modules/services/eden.nix
    ../../modules/services/jellyfin.nix
    ../../modules/services/public-site.nix
    ../../modules/services/syncthing.nix
    ../../modules/services/samba.nix

    ../../routes
  ];

  homelab = {
    domain = "therealrishabh.com";
    internalSubdomain = "internal";

    tailnetIp = "100.73.159.103";
    tailnetIpv6 = "fd7a:115c:a1e0::6b32:9f68";

    acme = {
      enable = true;
      email = "rishabhgoel0213@gmail.com";
    };

    secrets.enable = true;

    publicTunnel = {
      enable = true;
      tunnelId = "b0bf2296-d35d-4d03-aca8-ee3d4ecaa8fa";
    };

    privateDns.enable = true;
    remotePhone.enable = true;
    canvasBridge.enable = true;

    backrest = {
      enable = true;
      repository = "sftp:u614006@u614006.your-storagebox.de:/home/restic/nixos-pc";
      sshTarget = "u614006@u614006.your-storagebox.de";
      sshPort = 23;
    };

    vaultwarden.enable = true;
    eden.enable = true;
    jellyfin.enable = true;
    syncthing.enable = true;
    samba.enable = true;
  };

  system.stateVersion = "26.05";
}
