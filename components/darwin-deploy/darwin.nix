{
  lib,
  pkgs,
  ...
}:

let
  cachePublicKey = lib.removeSuffix "\n" (builtins.readFile ./cache-public-key.txt);
  serverSshPublicKey = lib.removeSuffix "\n" (builtins.readFile ./server-ssh-public-key.txt);
  pfRunner = pkgs.writeShellScript "tailscale-ssh-pf" ''
    set -eu

    /sbin/pfctl -nf /etc/pf.conf
    /sbin/pfctl -f /etc/pf.conf

    if ! /sbin/pfctl -s info | /usr/bin/grep -q '^Status: Enabled'; then
      /sbin/pfctl -e
    fi

    /sbin/pfctl -a com.rishabhgoel.tailscale-ssh -sr \
      | /usr/bin/grep -q 'block return in quick proto tcp from any to any port = 22'
  '';
in
{
  nix.settings.trusted-public-keys = lib.mkAfter [ cachePublicKey ];

  users.users.rishabhgoel.openssh.authorizedKeys.keys = [ serverSshPublicKey ];

  environment.etc = {
    "pf.conf".source = ./pf.conf;
    "pf.anchors/com.rishabhgoel.tailscale-ssh".source = ./tailscale-ssh.pf;
  };

  launchd.daemons."com.rishabhgoel.tailscale-ssh-pf".serviceConfig = {
    Label = "com.rishabhgoel.tailscale-ssh-pf";
    ProgramArguments = [ "${pfRunner}" ];
    RunAtLoad = true;
    ProcessType = "Background";
  };

  services.openssh = {
    enable = true;
    extraConfig = ''
      PasswordAuthentication no
      KbdInteractiveAuthentication no
      PermitRootLogin no
      AllowUsers rishabhgoel
    '';
  };
}
