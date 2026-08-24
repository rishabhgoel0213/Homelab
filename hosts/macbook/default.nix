{ ... }:

{
  imports = [
    ../../platform/darwin/base.nix
    ../../profiles/darwin/workstation.nix
    ../../components/darwin-deploy/darwin.nix
  ];

  homelab.apps = {
    tabby.packageSource = "prebuilt";
    zen.packageSource = "source";
  };
}
