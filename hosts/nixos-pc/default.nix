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
    ../../components/claude/nixos.nix
    ../../components/antigravity/nixos.nix
    ../../components/google-workspace/nixos.nix
    ../../components/apple-dev/nixos.nix
    ../../components/tasks/nixos.nix
    ../../components/memory/nixos.nix
    ../../components/skills/nixos.nix
    ../../platform/nixos/containers.nix
    ../../platform/nixos/filesystem.nix
    ../../components/projects/nixos.nix
    ../../components/darwin-deploy/nixos.nix
    ../../platform/nixos/gpu.nix
    ../../components/workmode/nixos.nix
    ../../components/brick-admin/nixos.nix
    ../../platform/nixos/secrets.nix
    ../../components/tailscale/dns.nix
    ../../components/cloudflare/nixos.nix
    ../../components/tailscale/api.nix

    ../../components/vaultwarden/nixos.nix
    ../../components/matrix/nixos.nix
    ../../components/backrest/nixos.nix
    ../../components/canvas-bridge/nixos.nix
    ../../components/jellyfin/nixos.nix
    ../../components/local-models/qwen-image-2.1/nixos.nix
    ../../components/jupyterlab/nixos.nix
    ../../components/t3code/nixos.nix
    ../../components/vscodium/remote-server.nix
    ../../components/syncthing/nixos.nix
    ../../components/samba/nixos.nix
    ../../components/zen/space-router/nixos.nix

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
    canvasBridge.enable = true;

    backrest = {
      enable = true;
      repository = "sftp:u614006@u614006.your-storagebox.de:/home/restic/nixos-pc";
      sshTarget = "u614006@u614006.your-storagebox.de";
      sshPort = 23;
    };

    vaultwarden.enable = true;
    matrix.enable = true;
    jellyfin.enable = true;
    qwenImage21.enable = true;
    jupyterlab.enable = true;
    projectPages.enable = true;
    t3code.enable = true;
    syncthing.enable = true;
    samba.enable = true;
    tasks.enable = true;
    memory.enable = true;
    skills.enable = true;
    zenSpaceRouter.enable = true;
  };

  system.stateVersion = "26.05";
}
