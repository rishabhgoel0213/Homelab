{ ... }:

{
  imports = [
    ../../modules/darwin/base.nix
    ../../modules/darwin/apps.nix
    ../../modules/darwin/tailscale.nix
  ];

  nix-homebrew = {
    enable = true;
    enableRosetta = false;
    user = "rishabhgoel";

    # The existing Apple-silicon Homebrew installation, if present, will be
    # adopted on the first activation. Taps stay mutable until the current
    # installation is inventoried during the later deployment window.
    autoMigrate = true;
    mutableTaps = true;
  };
}
