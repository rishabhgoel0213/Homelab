{ lib, pkgs, ... }:
let package = pkgs.callPackage ./package.nix { };
in {
  environment.systemPackages = [ package ];
  environment.etc."brick-admin-root".source = "${package.gate}/libexec/brick-admin-root";
  environment.etc."ssh/sshd_config.d/000-brick-admin.conf".text = "PermitRootLogin no\n";
  security.sudo.extraConfig = lib.mkAfter ''
    @includedir /var/db/brick-admin/sudoers.d
  '';
  system.activationScripts.postActivation.text = ''
    /usr/bin/install -d -m 0700 -o root -g wheel /var/db/brick-admin /var/db/brick-admin/sudoers.d
  '';
}
