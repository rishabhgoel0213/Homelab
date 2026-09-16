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
      mkdir -p "$state_dir/sessions" "$state_dir/logs"
      session_dir="$(mktemp -d "$state_dir/sessions/session.XXXXXX")"
      webdriver_profile="$session_dir/firefox_devtools_mcp_profile"

      # Invoked indirectly by the traps below.
      # shellcheck disable=SC2329
      cleanup() {
        trap - EXIT INT TERM HUP

        # firefox-devtools-mcp can exit before its launched browser does. Match
        # only the unique, throwaway profile for this session so the user's
        # regular Zen process and other test sessions are never touched.
        /usr/bin/pkill -TERM -f "$webdriver_profile" 2>/dev/null || true
        for _ in {1..20}; do
          if ! /usr/bin/pgrep -f "$webdriver_profile" >/dev/null 2>&1; then
            break
          fi
          sleep 0.1
        done
        /usr/bin/pkill -KILL -f "$webdriver_profile" 2>/dev/null || true
        rm -rf -- "$session_dir"
      }
      trap cleanup EXIT INT TERM HUP

      status=0
      firefox-devtools-mcp \
        --firefoxPath ${lib.escapeShellArg "${selectedPackage}/Applications/Zen.app/Contents/MacOS/zen"} \
        --profilePath "$session_dir" \
        --viewport ${lib.escapeShellArg cfg.devtoolsMcp.viewport} \
        --startUrl about:blank \
        --toolPreset mozilla \
        --env MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1 \
        --pref remote.prefs.recommended=false \
        --pref zen.welcome-screen.seen=true \
        --firefoxArg=--no-remote \
        --outputFile "$state_dir/logs/firefox.log" \
        --logFile "$state_dir/logs/mcp.log" \
        "$@" || status=$?
      exit "$status"
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
