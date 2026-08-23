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
