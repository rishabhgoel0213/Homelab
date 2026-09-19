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

        icon = lib.mkOption {
          type = lib.types.nullOr lib.types.path;
          default = null;
          description = "Optional ICNS icon used by the generated macOS application bundle.";
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

        remoteHost = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Optional SSH host opened automatically by this preset.";
        };

        remotePath = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Default path opened on the preset's SSH host.";
        };

        localPathPrefix = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = "Optional local project prefix mapped to remotePath by the launcher.";
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
        icon
        mutableExtensions
        localPathPrefix
        remoteHost
        remotePath
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
        install -d -m 0700 -o ${user} -g staff \
          "$data_root/extension-data/ms-toolsai.jupyter/temp"
        ${lib.optionalString preset.mutableExtensions ''
          install_mutable_extensions \
            "$data_root/extensions" \
            ${packages.managedExtensionDir}/share/vscode/extensions
        ''}
        install_settings "$data_root/User/settings.json" ${packages.settingsFile}
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
        {
          assertion = (preset.remoteHost == null) == (preset.remotePath == null);
          message = "VSCodium preset ${name} must set remoteHost and remotePath together";
        }
        {
          assertion = preset.remoteHost == null || preset.workspace == null;
          message = "VSCodium preset ${name} cannot set both remoteHost and workspace";
        }
        {
          assertion = preset.localPathPrefix == null || preset.remoteHost != null;
          message = "VSCodium preset ${name} localPathPrefix requires remoteHost";
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

      install_settings() {
        target="$1"
        source="$2"

        # Older deployments linked settings.json directly into the immutable
        # Nix store. Replace only that known managed link; never overwrite an
        # unrelated symlink that happens to be at the same path.
        if [[ -L "$target" ]]; then
          current_source="$(readlink "$target")"
          case "$current_source" in
            /nix/store/*)
              rm -f "$target"
              ;;
            *)
              echo "Refusing to replace unmanaged VSCodium settings link at $target" >&2
              exit 1
              ;;
          esac
        elif [[ -e "$target" && ! -f "$target" ]]; then
          echo "Refusing to replace unmanaged VSCodium settings path at $target" >&2
          exit 1
        fi

        # VSCodium occasionally rewrites settings.json even when the effective
        # settings are unchanged. Install the declared baseline as a writable
        # regular file so those writes succeed. Each deployment restores it.
        install -m 0600 -o ${user} -g staff "$source" "$target"
      }

      install_mutable_extensions() {
        extensions_root="$1"
        managed_source="$2"
        managed_manifest="$extensions_root/.homelab-managed-extensions"
        extension_cache="$extensions_root/extensions.json"

        install -d -m 0700 -o ${user} -g staff "$extensions_root"

        if [[ -f "$managed_manifest" ]]; then
          while IFS= read -r extension_name; do
            case "$extension_name" in
              ""|*[!A-Za-z0-9._-]*)
                echo "Refusing invalid managed VSCodium extension name: $extension_name" >&2
                exit 1
                ;;
            esac
            extension_target="$extensions_root/$extension_name"
            if [[ -L "$extension_target" ]]; then
              extension_source="$(readlink "$extension_target")"
              case "$extension_source" in
                /nix/store/*) rm -f "$extension_target" ;;
              esac
            fi
          done < "$managed_manifest"
        fi

        manifest_tmp="$(mktemp "$extensions_root/.homelab-managed-extensions.XXXXXX")"
        for extension_source in "$managed_source"/*; do
          [[ -d "$extension_source" ]] || continue
          extension_name="''${extension_source##*/}"
          extension_target="$extensions_root/$extension_name"
          if [[ -e "$extension_target" && ! -L "$extension_target" ]]; then
            echo "Refusing to replace unmanaged VSCodium extension at $extension_target" >&2
            rm -f "$manifest_tmp"
            exit 1
          fi
          ln -sfn "$extension_source" "$extension_target"
          chown -h ${user}:staff "$extension_target"
          printf '%s\n' "$extension_name" >> "$manifest_tmp"
        done

        chown ${user}:staff "$manifest_tmp"
        chmod 0600 "$manifest_tmp"
        mv -f "$manifest_tmp" "$managed_manifest"

        cache_tmp="$(mktemp "$extensions_root/extensions.json.XXXXXX")"
        if [[ -f "$extension_cache" ]] && ${pkgs.jq}/bin/jq -e 'type == "array"' "$extension_cache" >/dev/null; then
          ${pkgs.jq}/bin/jq -s '
            .[0] as $managed
            | .[1] as $existing
            | ($managed | map(.identifier.id)) as $managed_ids
            | $managed + ($existing | map(select(.identifier.id as $id | ($managed_ids | index($id)) == null)))
          ' "$managed_source/extensions.json" "$extension_cache" > "$cache_tmp"
        else
          cp "$managed_source/extensions.json" "$cache_tmp"
        fi
        chown ${user}:staff "$cache_tmp"
        chmod 0600 "$cache_tmp"
        mv -f "$cache_tmp" "$extension_cache"
      }

      ${activation}
    '';
  };
}
