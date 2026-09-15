{
  config,
  lib,
  macbookPackages,
  pkgs,
  ...
}:

let
  cfg = config.homelab.apps.zen;
  selectedPackage =
    if cfg.packageSource == "source" then macbookPackages.zenSource else macbookPackages.zen;
  devtoolsMcpPackage = pkgs.callPackage ./devtools-mcp/package.nix { };
  zenDevtoolsMcp = pkgs.writeShellApplication {
    name = "zen-devtools-mcp";
    runtimeInputs = [
      devtoolsMcpPackage
      pkgs.geckodriver
    ];
    text = ''
      umask 077
      state_dir="''${ZEN_DEVTOOLS_STATE_DIR:-$HOME/Library/Application Support/Homelab/ZenDevTools}"
      profile_dir="$state_dir/profile"
      mkdir -p "$profile_dir" "$state_dir/logs"

      exec firefox-devtools-mcp \
        --firefoxPath ${lib.escapeShellArg "${selectedPackage}/Applications/Zen.app/Contents/MacOS/zen"} \
        --profilePath "$profile_dir" \
        --viewport ${lib.escapeShellArg cfg.devtoolsMcp.viewport} \
        --startUrl about:blank \
        --toolPreset mozilla \
        --env MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1 \
        --pref remote.prefs.recommended=false \
        --firefoxArg=--no-remote \
        --outputFile "$state_dir/logs/firefox.log" \
        --logFile "$state_dir/logs/mcp.log"
    '';
  };
in
{
  imports = [ ./managed-sidebar.nix ];

  options.homelab.apps.zen.packageSource = lib.mkOption {
    type = lib.types.enum [
      "prebuilt"
      "source"
    ];
    default = "prebuilt";
    description = "Whether to use the pinned upstream bundle or the server-cross-compiled source bundle.";
  };

  options.homelab.apps.zen.devtoolsMcp = {
    enable = lib.mkEnableOption "isolated Zen browser-chrome automation over Mozilla Firefox DevTools MCP";
    viewport = lib.mkOption {
      type = lib.types.strMatching "[0-9]+x[0-9]+";
      default = "1440x900";
      description = "Logical viewport for the dedicated Zen visual-testing profile.";
    };
  };

  config = {
    environment.systemPackages = [
      selectedPackage
    ]
    ++ lib.optional cfg.devtoolsMcp.enable zenDevtoolsMcp;

    # Mozilla supports macOS enterprise policy through this system preference
    # domain. Keeping policy outside Zen.app preserves the vendor signature.
    system.defaults.CustomSystemPreferences."/Library/Preferences/org.mozilla.firefox" = {
      EnterprisePoliciesEnabled = true;
      DisableAppUpdate = true;
      ExtensionSettings = {
        "*".installation_mode = "allowed";
        "{446900e4-71c2-419f-a6a7-df9c091e268b}" = {
          installation_mode = "force_installed";
          install_url = "https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi";
        };
      };
    };
  };
}
