{ ... }:

{
  imports = [
    ../../platform/darwin/base.nix
    ../../profiles/darwin/workstation.nix
    ../../components/tailscale/darwin.nix
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

  homelab.apps = {
    tabby.packageSource = "prebuilt";
    zen.packageSource = "prebuilt";
  };
}
