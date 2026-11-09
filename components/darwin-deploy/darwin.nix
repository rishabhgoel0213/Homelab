{
  lib,
  ...
}:

let
  cachePublicKey = lib.removeSuffix "\n" (builtins.readFile ./cache-public-key.txt);
  serverSshPublicKey = lib.removeSuffix "\n" (builtins.readFile ./server-ssh-public-key.txt);
in
{
  nix.settings.trusted-public-keys = lib.mkAfter [ cachePublicKey ];

  users.users.rishabhgoel.openssh.authorizedKeys.keys = [ serverSshPublicKey ];

  # Remote Login's PAM service ACL is separate from sshd AllowUsers and keys.
  # Keep access explicit when Brick enrollment removes admin membership.
  system.activationScripts.postActivation.text = lib.mkAfter ''
    if ! /usr/bin/dscl . -read /Groups/com.apple.access_ssh >/dev/null 2>&1; then
      /usr/sbin/dseditgroup -o create com.apple.access_ssh
    fi
    /usr/sbin/dseditgroup -o edit -a rishabhgoel -t user com.apple.access_ssh
  '';

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
