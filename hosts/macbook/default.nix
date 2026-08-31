{ ... }:

{
  imports = [
    ../../platform/darwin/base.nix
    ../../profiles/darwin/coursework.nix
    ../../profiles/darwin/workstation.nix
    ../../components/darwin-deploy/darwin.nix
  ];

  homelab.apps = {
    tabby.packageSource = "prebuilt";
    zen.packageSource = "source";
  };

  homelab.coursework.cmsc216 = {
    enable = true;
    directoryId = "r1shabhg";
  };
}
