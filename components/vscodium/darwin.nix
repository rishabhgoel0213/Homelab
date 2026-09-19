{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.apps.vscodium;
  user = "rishabhgoel";
  userHome = "/Users/${user}";

  presetModule = lib.types.submodule (
    { name, ... }:
    {
      options = {
        enable = lib.mkEnableOption "the ${name} VSCodium preset" // {
          default = true;
        };

        displayName = lib.mkOption {
          type = lib.types.str;
          default = "VSCodium ${name}";
          description = "macOS application display name for this preset.";
        };

        bundleIdentifier = lib.mkOption {
          type = lib.types.str;
          default = "com.therealrishabh.vscodium.${name}";
          description = "Unique macOS bundle identifier for this preset.";
        };

        dataRoot = lib.mkOption {
          type = lib.types.str;
          default = "${userHome}/Library/Application Support/Homelab VSCodium/${name}";
          description = "Mutable VSCodium user-data directory for this preset.";
        };

        bundles = lib.mkOption {
          type = lib.types.listOf lib.types.str;
          default = [ ];
          description = "Named extension bundles included in this preset.";
        };

        extensions = lib.mkOption {
          type = lib.types.listOf lib.types.package;
          default = [ ];
          description = "Additional extensions included only in this preset.";
        };

        settings = lib.mkOption {
          type = lib.types.attrs;
          default = { };
          description = "Settings merged over the common managed settings.";
        };

        workspace = lib.mkOption {
          type = lib.types.nullOr lib.types.package;
          default = null;
          description = "Optional fixed workspace opened by this preset.";
        };

        workspaceLinkName = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Optional managed workspace link created in the preset data root.";
        };

        mutableExtensions = lib.mkOption {
          type = lib.types.bool;
          default = false;
          description = "Allow this preset to install extensions into a private mutable directory.";
        };

        appVersion = lib.mkOption {
          type = lib.types.str;
          default = "1.0";
          description = "Version exposed by the generated macOS application bundle.";
        };

      };
    }
  );

  enabledPresets = lib.filterAttrs (_: preset: preset.enable) cfg.presets;
  resolvedExtensions =
    preset:
    lib.unique (
      lib.concatMap (bundle: cfg.extensionBundles.${bundle}) preset.bundles ++ preset.extensions
    );
  packageSets = lib.mapAttrs (
    name: preset:
    pkgs.callPackage ./package.nix {
      presetName = name;
      inherit (preset)
        appVersion
        bundleIdentifier
        dataRoot
        displayName
        mutableExtensions
        workspace
        ;
      extensions = resolvedExtensions preset;
      settings = cfg.commonSettings // preset.settings;
    }
  ) enabledPresets;

  dispatcher = pkgs.callPackage ./dispatcher.nix {
    presets = lib.mapAttrs (name: preset: {
      inherit (preset) displayName;
      cli = packageSets.${name}.cli;
    }) enabledPresets;
  };

  activation = lib.concatStringsSep "\n" (
    lib.mapAttrsToList (
      name: preset:
      let
        packages = packageSets.${name};
        workspaceLink =
          if preset.workspace == null || preset.workspaceLinkName == null then
            ""
          else
            ''
              manage_link \
                ${lib.escapeShellArg "${preset.dataRoot}/${preset.workspaceLinkName}"} \
                ${lib.escapeShellArg (toString preset.workspace)}
            '';
      in
      ''
        data_root=${lib.escapeShellArg preset.dataRoot}
        install -d -m 0700 -o ${user} -g staff "$data_root" "$data_root/User"
        ${lib.optionalString preset.mutableExtensions ''
          install -d -m 0700 -o ${user} -g staff "$data_root/extensions"
        ''}
        manage_link "$data_root/User/settings.json" ${packages.settingsFile}
        ${workspaceLink}
      ''
    ) enabledPresets
  );
in
{
  options.homelab.apps.vscodium = {
    enable = lib.mkEnableOption "declarative isolated VSCodium presets";

    commonSettings = lib.mkOption {
      type = lib.types.attrs;
      default = {
        "extensions.autoCheckUpdates" = false;
        "extensions.autoUpdate" = false;
        "security.workspace.trust.enabled" = true;
        "telemetry.telemetryLevel" = "off";
        "update.mode" = "none";
        "workbench.enableExperiments" = false;
      };
      description = "Managed settings shared by every VSCodium preset.";
    };

    extensionBundles = lib.mkOption {
      type = lib.types.attrsOf (lib.types.listOf lib.types.package);
      default = { };
      description = "Reusable named groups of VSCodium extensions.";
    };

    presets = lib.mkOption {
      type = lib.types.attrsOf presetModule;
      default = { };
      description = "Isolated VSCodium application presets.";
    };

    generated = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            package = lib.mkOption {
              type = lib.types.package;
              readOnly = true;
              internal = true;
            };
            cliPackage = lib.mkOption {
              type = lib.types.package;
              readOnly = true;
              internal = true;
            };
            codiumPackage = lib.mkOption {
              type = lib.types.package;
              readOnly = true;
              internal = true;
            };
          };
        }
      );
      readOnly = true;
      internal = true;
      description = "Generated packages for enabled VSCodium presets.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = lib.flatten (
      lib.mapAttrsToList (name: preset: [
        {
          assertion = builtins.match "[A-Za-z0-9._-]+" name != null;
          message = "homelab.apps.vscodium preset names must be shell-safe";
        }
        {
          assertion = lib.all (bundle: builtins.hasAttr bundle cfg.extensionBundles) preset.bundles;
          message = "VSCodium preset ${name} references an unknown extension bundle";
        }
        {
          assertion = lib.hasPrefix "${userHome}/" preset.dataRoot;
          message = "VSCodium preset ${name} dataRoot must be inside ${userHome}";
        }
      ]) cfg.presets
    );

    homelab.apps.vscodium.generated = lib.mapAttrs (name: _: {
      package = packageSets.${name}.app;
      cliPackage = packageSets.${name}.cli;
      codiumPackage = packageSets.${name}.codium;
    }) enabledPresets;

    environment.systemPackages = [
      dispatcher
    ]
    ++ lib.flatten (
      lib.mapAttrsToList (_: packages: [
        packages.app
        packages.cli
      ]) packageSets
    );

    system.activationScripts.postActivation.text = lib.mkAfter ''
      manage_link() {
        target="$1"
        source="$2"
        if [[ -e "$target" && ! -L "$target" ]]; then
          echo "Refusing to replace unmanaged VSCodium file at $target" >&2
          exit 1
        fi
        ln -sfn "$source" "$target"
        chown -h ${user}:staff "$target"
      }

      ${activation}
    '';
  };
}
