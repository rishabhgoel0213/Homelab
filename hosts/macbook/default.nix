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
    zen = {
      packageSource = "source";
      devtoolsMcp.enable = true;
      managedSidebar = {
        enable = true;
        preferences = {
          "zen.workspaces.continue-where-left-off" = true;
          "zen.workspaces.separate-essentials" = true;
        };
        spaces.General = {
          icon = "🏠";
          position = 0;
        };
      };
    };
  };

  homelab.coursework.cmsc216 = {
    enable = true;
    directoryId = "r1shabhg";
  };
}
