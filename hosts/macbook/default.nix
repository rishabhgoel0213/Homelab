{ pkgs, ... }:

let
  projectsExtension = pkgs.callPackage ../../components/vscodium/projects-extension/package.nix { };
  extensionSets = import ../../components/vscodium/extensions.nix {
    inherit pkgs projectsExtension;
  };
in
{
  imports = [
    ./zen-spaces.nix
    ../../platform/darwin/base.nix
    ../../profiles/darwin/coursework.nix
    ../../profiles/darwin/workstation.nix
    ../../components/darwin-deploy/darwin.nix
  ];

  homelab.apps = {
    tabby.packageSource = "prebuilt";
    vscodium = {
      enable = true;

      extensionBundles = {
        inherit (extensionSets)
          c
          core
          notebooks
          python
          rust
          web
          ;
        remote = extensionSets.remoteClient;
      };

      presets = {
        general = {
          displayName = "VSCodium";
          bundleIdentifier = "com.therealrishabh.vscodium";
          icon = ../../components/vscodium/icons/VSCodium-Remote.icns;
          bundles = [
            "core"
            "c"
            "notebooks"
            "python"
            "rust"
            "web"
            "remote"
          ];
          remoteHost = "nixos-pc";
          remotePath = "/home/rishabh/Projects";
          localPathPrefix = "/Users/rishabhgoel/Projects";
          settings."remote.SSH.remotePlatform".nixos-pc = "linux";
          appVersion = "2026.2";
        };

        local = {
          displayName = "VSCodium Local";
          bundleIdentifier = "com.therealrishabh.vscodium.local";
          icon = ../../components/vscodium/icons/VSCodium-Local.icns;
          dataRoot = "/Users/rishabhgoel/Library/Application Support/Homelab VSCodium/scratch";
          mutableExtensions = true;
          appVersion = "2026.2";
        };
      };
    };
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
