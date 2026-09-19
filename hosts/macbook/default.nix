{ pkgs, ... }:

let
  projectsExtension = pkgs.callPackage ../../components/vscodium/projects-extension/package.nix { };
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
        core = [
          projectsExtension
          pkgs.vscode-extensions.editorconfig.editorconfig
          pkgs.vscode-extensions.jnoortheen.nix-ide
          pkgs.vscode-extensions.mkhl.direnv
          pkgs.vscode-extensions.redhat.vscode-yaml
          pkgs.vscode-extensions.tamasfe.even-better-toml
        ];
        c = [ pkgs.vscode-extensions.llvm-vs-code-extensions.vscode-clangd ];
        notebooks = [
          pkgs.vscode-extensions.ms-toolsai.jupyter
          pkgs.vscode-extensions.ms-toolsai.jupyter-renderers
        ];
        python = [
          pkgs.vscode-extensions.ms-python.black-formatter
          pkgs.vscode-extensions.ms-python.debugpy
          pkgs.vscode-extensions.ms-python.python
          pkgs.vscode-extensions.ms-python.vscode-python-envs
        ];
        rust = [ pkgs.vscode-extensions.rust-lang.rust-analyzer ];
        web = [
          pkgs.vscode-extensions.dbaeumer.vscode-eslint
          pkgs.vscode-extensions.esbenp.prettier-vscode
        ];
      };

      presets = {
        general = {
          displayName = "VSCodium";
          bundleIdentifier = "com.therealrishabh.vscodium";
          bundles = [
            "core"
            "c"
            "notebooks"
            "python"
            "rust"
            "web"
          ];
        };

        research = {
          displayName = "Research IDE";
          bundleIdentifier = "com.therealrishabh.vscodium.research";
          bundles = [
            "core"
            "notebooks"
            "python"
          ];
        };

        scratch = {
          displayName = "VSCodium Scratch";
          bundleIdentifier = "com.therealrishabh.vscodium.scratch";
          mutableExtensions = true;
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
