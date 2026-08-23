{
  config,
  lib,
  pkgs,
  ...
}:

{
  imports = [
    ./hardware-configuration.nix

    ../../platform/shared/options.nix
    ../../platform/nixos/ingress.nix

    ../../platform/nixos/base.nix
    ../../platform/nixos/agents.nix
    ../../components/codex/nixos.nix
    ../../components/pi/nixos.nix
    ../../platform/nixos/containers.nix
    ../../platform/nixos/filesystem.nix
    ../../components/projects/nixos.nix
    ../../components/darwin-deploy/nixos.nix
    ../../platform/nixos/gpu.nix
    ../../components/remote-phone/nixos.nix
    ../../platform/nixos/secrets.nix
    ../../components/tailscale/dns.nix
    ../../components/cloudflare/nixos.nix
    ../../components/tailscale/api.nix
    ../../components/vscode-remote/nixos.nix

    ../../components/vaultwarden/nixos.nix
    ../../components/matrix/nixos.nix
    ../../components/backrest/nixos.nix
    ../../components/canvas-bridge/nixos.nix
    ../../components/kicad/nixos.nix
    ../../components/jellyfin/nixos.nix
    ../../components/local-models/bonsai/nixos.nix
    ../../components/local-models/mach1/nixos.nix
    ../../components/local-models/nemotron-lightning/nixos.nix
    ../../components/jupyterlab/nixos.nix
    ../../components/t3code/nixos.nix
    ../../components/blog/nixos.nix
    ../../components/syncthing/nixos.nix
    ../../components/singlemail/nixos.nix
    ../../components/samba/nixos.nix

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
    matrix.enable = true;
    pi.courier.enable = true;
    kicad.enable = true;
    jellyfin.enable = true;
    bonsaiTernary.enable = true;
    mach1Additive.enable = true;
    nemotronLightning.enable = true;
    jupyterlab.enable = true;
    blogSite.enable = true;
    t3code = {
      enable = true;
      sourceCheckout = "/home/rishabh/Projects/t3code";
      revision = "fef71fb0c1e14b16d0e4b82159f71b9a9d2e9eb3";
    };
    syncthing.enable = true;
    singlemail.enable = true;
    samba.enable = true;
  };

  system.stateVersion = "26.05";
}
