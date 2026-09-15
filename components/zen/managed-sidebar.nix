{
  config,
  lib,
  ...
}:

let
  inherit (lib) mkIf mkOption types;
  cfg = config.homelab.apps.zen.managedSidebar;

  stableId =
    kind: name:
    let
      hash = builtins.hashString "sha256" "homelab-zen-${kind}-${name}";
    in
    "{${builtins.substring 0 8 hash}-${builtins.substring 8 4 hash}-4${builtins.substring 13 3 hash}-a${builtins.substring 17 3 hash}-${builtins.substring 20 12 hash}}";

  modeOption =
    collection: default:
    mkOption {
      type = types.enum [
        "merge"
        "authoritative"
      ];
      inherit default;
      description = "Whether declared ${collection} are merged with or replace mutable ${collection}.";
    };

  containerType = types.submodule (
    { name, ... }:
    {
      options = {
        id = mkOption {
          type = types.str;
          default = stableId "container" name;
          description = "Stable cross-profile GUID for this container.";
        };
        builtin = mkOption {
          type = types.nullOr (types.ints.between 1 4);
          default = null;
          description = "Reuse one of Firefox's four built-in container identities.";
        };
        name = mkOption {
          type = types.str;
          default = name;
          description = "Display name.";
        };
        icon = mkOption {
          type = types.str;
          default = "fingerprint";
          description = "Firefox container icon name.";
        };
        color = mkOption {
          type = types.str;
          default = "blue";
          description = "Firefox container color name.";
        };
        position = mkOption {
          type = types.int;
          default = 1000;
          description = "Stable ordering key used while applying the manifest.";
        };
      };
    }
  );

  spaceType = types.submodule (
    { name, ... }:
    {
      options = {
        id = mkOption {
          type = types.str;
          default = stableId "space" name;
          description = "Stable Zen Space UUID.";
        };
        name = mkOption {
          type = types.str;
          default = name;
          description = "Display name.";
        };
        icon = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Emoji, data URL, or Zen icon URL.";
        };
        container = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Key from managedSidebar.containers, or null for the default container.";
        };
        theme = mkOption {
          type = types.nullOr types.unspecified;
          default = null;
          description = "Raw Zen theme object, including gradientColors, opacity, and texture.";
        };
        position = mkOption {
          type = types.int;
          default = 1000;
          description = "Space ordering key.";
        };
      };
    }
  );

  folderType = types.submodule (
    { name, ... }:
    {
      options = {
        id = mkOption {
          type = types.str;
          default = stableId "folder" name;
          description = "Stable folder ID.";
        };
        name = mkOption {
          type = types.str;
          default = name;
          description = "Display name.";
        };
        space = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Containing Space key. Nested folders inherit this from their parent.";
        };
        parent = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Parent folder key for nested folders.";
        };
        icon = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Folder icon URL.";
        };
        live = mkOption {
          type = types.nullOr (
            types.submodule {
              options = {
                type = mkOption {
                  type = types.enum [
                    "rss"
                    "github"
                  ];
                  description = "Zen live-folder provider.";
                };
                state = mkOption {
                  type = types.unspecified;
                  default = { };
                  description = "Provider state passed to Zen, such as RSS URL or GitHub filters.";
                };
              };
            }
          );
          default = null;
          description = "Optional live-folder provider configuration.";
        };
        position = mkOption {
          type = types.int;
          default = 1000;
          description = "Ordering key within the Space or parent folder.";
        };
      };
    }
  );

  pinType = types.submodule (
    { name, ... }:
    {
      options = {
        id = mkOption {
          type = types.str;
          default = stableId "pin" name;
          description = "Stable pinned-tab ID.";
        };
        title = mkOption {
          type = types.str;
          default = name;
          description = "Initial title.";
        };
        url = mkOption {
          type = types.str;
          description = "Canonical URL restored when the pin is reset.";
        };
        icon = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Optional local/data icon URL.";
        };
        staticLabel = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Optional user-visible label that does not follow the page title.";
        };
        staticIcon = mkOption {
          type = types.bool;
          default = false;
          description = "Keep the declared icon instead of following the page favicon.";
        };
        essential = mkOption {
          type = types.bool;
          default = false;
          description = "Make this an Essential rather than a Space pin.";
        };
        defaultContainer = mkOption {
          type = types.bool;
          default = false;
          description = "Mark the tab as using Zen's default-container behavior.";
        };
        container = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Optional container key; otherwise inherit the containing Space container.";
        };
        space = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Containing Space key for a top-level pin.";
        };
        folder = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Containing folder key.";
        };
        position = mkOption {
          type = types.int;
          default = 1000;
          description = "Ordering key within its containing section.";
        };
      };
    }
  );

  splitType = types.submodule (
    { name, ... }:
    {
      options = {
        id = mkOption {
          type = types.str;
          default = stableId "split" name;
          description = "Stable split-view group ID.";
        };
        pins = mkOption {
          type = types.listOf types.str;
          description = "At least two managed pin keys shown in this split view.";
        };
        gridType = mkOption {
          type = types.enum [
            "grid"
            "hsep"
            "vsep"
          ];
          default = "grid";
          description = "Zen split layout.";
        };
        space = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Containing Space key.";
        };
        folder = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Optional containing folder key.";
        };
        position = mkOption {
          type = types.int;
          default = 1000;
          description = "Ordering key for the split group.";
        };
      };
    }
  );

  routeType = types.submodule (
    { name, ... }:
    {
      options = {
        id = mkOption {
          type = types.str;
          default = stableId "route" name;
          description = "Stable routing-rule ID.";
        };
        reference = mkOption {
          type = types.str;
          description = "Text or regular expression matched against the target URL.";
        };
        matchType = mkOption {
          type = types.enum [
            "contains"
            "equal-to"
            "regex"
          ];
          default = "contains";
          description = "Zen URL matching behavior.";
        };
        space = mkOption {
          type = types.nullOr types.str;
          default = null;
          description = "Destination Space key, or null for the most recent Space.";
        };
        position = mkOption {
          type = types.int;
          default = 1000;
          description = "Rule priority; lower values match first.";
        };
      };
    }
  );

  effectiveContainerId =
    container:
    if container.builtin == null then container.id else "builtin-${toString container.builtin}";
  allRecordIds = [
    "layout"
  ]
  ++ lib.mapAttrsToList (_: effectiveContainerId) cfg.containers
  ++ lib.mapAttrsToList (_: item: item.id) cfg.spaces
  ++ lib.mapAttrsToList (_: item: item.id) cfg.folders
  ++ lib.mapAttrsToList (_: item: item.id) cfg.pins
  ++ lib.mapAttrsToList (_: item: item.id) cfg.splits;
  splitPins = lib.concatMap (split: split.pins) (lib.attrValues cfg.splits);
  has = collection: key: key == null || builtins.hasAttr key collection;
  referencesAreValid =
    lib.all (space: has cfg.containers space.container) (lib.attrValues cfg.spaces)
    && lib.all (
      folder:
      has cfg.spaces folder.space
      && has cfg.folders folder.parent
      && (folder.space != null || folder.parent != null)
    ) (lib.attrValues cfg.folders)
    && lib.all (
      value:
      value.pin.essential
      || value.pin.space != null
      || value.pin.folder != null
      || builtins.elem value.name splitPins
    ) (lib.mapAttrsToList (name: pin: { inherit name pin; }) cfg.pins)
    && lib.all (
      pin: has cfg.containers pin.container && has cfg.spaces pin.space && has cfg.folders pin.folder
    ) (lib.attrValues cfg.pins)
    && lib.all (
      split:
      builtins.length split.pins >= 2
      && lib.all (pin: builtins.hasAttr pin cfg.pins) split.pins
      && has cfg.spaces split.space
      && has cfg.folders split.folder
      && (split.space != null || split.folder != null)
    ) (lib.attrValues cfg.splits)
    && lib.all (route: has cfg.spaces route.space) (lib.attrValues cfg.routes)
    && has cfg.spaces cfg.defaultExternalSpace;

  manifest = {
    version = 1;
    inherit (cfg)
      containers
      defaultExternalSpace
      disableFirefoxSync
      folders
      modes
      pinRemoval
      pins
      routes
      spaces
      splits
      ;
  };
  manifestJSON = builtins.toJSON manifest;
  preferenceValues =
    cfg.preferences
    // lib.optionalAttrs (cfg.containers != { }) {
      "privacy.userContext.enabled" = true;
      "privacy.userContext.ui.enabled" = true;
    };
  managedPreferences = lib.mapAttrs (_: value: {
    Value = value;
    Status = "locked";
  }) preferenceValues;
in
{
  options.homelab.apps.zen.managedSidebar = {
    enable = lib.mkEnableOption "declarative Zen Spaces and sidebar topology";

    modes = mkOption {
      type = types.submodule {
        options = {
          containers = modeOption "containers" "merge";
          spaces = modeOption "Spaces" "authoritative";
          pins = modeOption "pins and Essentials" "authoritative";
          folders = modeOption "folders and live folders" "authoritative";
          splits = modeOption "split views" "authoritative";
          routes = modeOption "routing rules" "authoritative";
        };
      };
      default = { };
      description = "Per-collection reconciliation policy.";
    };

    pinRemoval = mkOption {
      type = types.enum [
        "demote"
        "remove"
      ];
      default = "demote";
      description = "What authoritative mode does with undeclared pins: preserve them as normal tabs or close them.";
    };

    disableFirefoxSync = mkOption {
      type = types.bool;
      default = true;
      description = "Disable Zen's Spaces Sync engine in the managed profile to prevent remote state from fighting Nix.";
    };

    preferences = mkOption {
      type = types.attrsOf types.unspecified;
      default = { };
      description = "Additional Firefox or Zen preferences enforced through Mozilla enterprise policy.";
    };

    containers = mkOption {
      type = types.attrsOf containerType;
      default = { };
      description = "Named contextual identities referenced by Spaces and pins.";
    };
    spaces = mkOption {
      type = types.attrsOf spaceType;
      default = { };
      description = "Declarative Zen Spaces.";
    };
    folders = mkOption {
      type = types.attrsOf folderType;
      default = { };
      description = "Declarative, nestable normal and live folders.";
    };
    pins = mkOption {
      type = types.attrsOf pinType;
      default = { };
      description = "Declarative pinned and Essential tabs.";
    };
    splits = mkOption {
      type = types.attrsOf splitType;
      default = { };
      description = "Declarative split views composed of managed pins.";
    };
    routes = mkOption {
      type = types.attrsOf routeType;
      default = { };
      description = "Declarative URL-to-Space routing rules.";
    };
    defaultExternalSpace = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Space key used for unmatched external links; null means the most recent Space.";
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = config.homelab.apps.zen.packageSource == "source";
        message = "homelab.apps.zen.managedSidebar requires packageSource = source";
      }
      {
        assertion = cfg.spaces != { };
        message = "homelab.apps.zen.managedSidebar requires at least one declared Space";
      }
      {
        assertion = builtins.length allRecordIds == builtins.length (lib.unique allRecordIds);
        message = "Zen managed sidebar IDs must be globally unique";
      }
      {
        assertion = referencesAreValid;
        message = "Zen managed sidebar contains an unknown or missing Space, folder, container, pin, split, or route reference";
      }
    ];

    environment.etc."zen/managed-sidebar.json".text = manifestJSON;
    system.defaults.CustomSystemPreferences."/Library/Preferences/org.mozilla.firefox".Preferences =
      managedPreferences;
  };
}
