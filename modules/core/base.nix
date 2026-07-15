{ config, lib, pkgs, ... }:

let
  cfg = config.homelab;
in
{
  boot.loader.systemd-boot.enable = true;
  boot.loader.systemd-boot.configurationLimit = 10;
  boot.loader.efi.canTouchEfiVariables = true;

  networking.hostName = "nixos-pc";
  networking.networkmanager = {
    enable = true;
    ensureProfiles = {
      environmentFiles = lib.optional cfg.secrets.enable config.sops.secrets."network-manager.env".path;
      profiles.OpenWrt = {
        connection = {
          id = "OpenWrt";
          permissions = "";
          type = "wifi";
          autoconnect = true;
        };
        ipv4.method = "auto";
        ipv6 = {
          addr-gen-mode = "default";
          method = "auto";
        };
        wifi = {
          mode = "infrastructure";
          ssid = "OpenWrt";
        };
        wifi-security = {
          auth-alg = "open";
          key-mgmt = "wpa-psk";
          psk = "$OPENWRT_WIFI_PSK";
        };
      };
    };
  };

  networking.firewall = {
    enable = true;
    allowedTCPPorts = [ 22 ];
    trustedInterfaces = [ "tailscale0" ];
  };

  time.timeZone = "America/New_York";
  i18n.defaultLocale = "en_US.UTF-8";

  hardware.enableRedistributableFirmware = true;

  services.openssh = {
    enable = true;
    settings = {
      PasswordAuthentication = false;
      PermitRootLogin = "no";
    };
  };

  services.tailscale = {
    enable = true;
    useRoutingFeatures = "client";
    extraSetFlags = [
      "--exit-node=nl-ams-wg-201.mullvad.ts.net"
      "--exit-node-allow-lan-access=false"
    ];
  };

  users.users.rishabh = {
    isNormalUser = true;
    description = "Rishabh Goel";
    extraGroups = [
      "networkmanager"
      "wheel"
    ];
    openssh.authorizedKeys.keys = [
      "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC/PCWA3njhJEoICf1s/nEhaDHlJrtIEWXn/TNrqGc5AUu76l1k9DYLP+AQVnYP9DnZCrQzfl3PVZkRO7SQl0tUXWFNFkb3h5kgl0reeO+Fwx/kGigv4EGZEwWypmRFO4TpuWsbcIOT0Hz0pbO545cgy4N3ZTOW5bf1wz9uQ+afU2MKTHloLgluV9f90dBWfNo8IWuMncjZ0jMlb3VU/i20LC+RbNt12ni6mEmFmVv1PNxyo46hfV4tE1sO0UKQ5gsVOic1pXP+3ocNNRdM5ZokhT5dkWn621DUbclGYjsSyNim2+51yA9X9Fy5dL8vXCU0IPFnHrVOql/Nii8YTMI1H3Kmc1APt8jJGjwRcFreVOEHt9vZx6GWlHA20QZLKjVIIheinJ3AdnXQwfbjajnkLSU8oUkYFWGLyATR6EyKfILNkJaFQ6y/1ogBKal3D98DXMp7JJwni2sB6sxc91khjN8hg6kAK2jf2Phnl7hIR+wz+eVdEbLcE9I3r8RuuzR50rNgiMcPhtIEBfleEAkIqbQBgGyJrnc0iqTg8dbdkgRconQLv4mhqAYKOcv8bAZiw8VW089yVxeTfm5+BY54xDFvK1iq5P2ZVjhfGLeOHPDuOWho/EWPFAr+CvjyHNGMHckbl/DijYhzzdssUqsVj/LqMhduXaOLFq3ZX8OApQ== rishabhgoel0213@gmail.com"
    ];
  };
  security.sudo.wheelNeedsPassword = false;

  nix = {
    settings.experimental-features = [
      "nix-command"
      "flakes"
    ];
    gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 14d";
    };
    optimise.automatic = true;
  };

  nixpkgs.config.allowUnfree = true;

  environment.systemPackages = with pkgs; [
    age
    bitwarden-cli
    bubblewrap
    caddy
    cloudflared
    curl
    direnv
    fzf
    git
    gh
    htop
    jq
    just
    openssh
    restic
    ripgrep
    rsync
    ssh-to-age
    sops
    tailscale
    tmux
    vim
    wget
  ];
}
