{ lib, ... }:

let
  macbookHostKey = lib.removeSuffix "\n" (builtins.readFile ./macbook-ssh-host-key.txt);
in
{
  # The private key is generated once on nixos-pc and never enters the Nix
  # store or Git. NixOS owns only the root-only state directory boundary.
  systemd.tmpfiles.rules = [
    "d /var/lib/homelab-nix-cache 0700 root root -"
  ];

  programs.ssh.knownHosts.macbook-tailnet = {
    hostNames = [
      "macbook.tail2f4d27.ts.net"
      "100.105.159.13"
    ];
    publicKey = macbookHostKey;
  };
}
