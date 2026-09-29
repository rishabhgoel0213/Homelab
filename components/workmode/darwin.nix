{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.homelab.workmode;
  abstand = pkgs.callPackage ./abstand.nix { };
  cli = pkgs.writeShellScriptBin "workmode" ''
    export WORKMODE_CONFIG=/etc/workmode/profiles.json
    export WORKMODE_COMMAND=/run/current-system/sw/bin/workmode
    exec ${pkgs.python3}/bin/python3 ${./workmode.py} "$@"
  '';
  plugin = pkgs.writeShellScript "workmode.15s.sh" ''
    # <xbar.title>Workmode</xbar.title>
    # <xbar.desc>Focus profiles and locked session status</xbar.desc>
    # <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
    exec /run/current-system/sw/bin/workmode menu
  '';
  login = pkgs.writeShellScript "workmode-login" ''
    set -eu
    plugin_dir=$(/usr/bin/defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)
    if [ -z "$plugin_dir" ]; then
      plugin_dir="$HOME/Library/Application Support/Workmode/SwiftBar"
      /usr/bin/defaults write com.ameba.SwiftBar PluginDirectory -string "$plugin_dir"
    fi
    # SwiftBar accepts tilde-prefixed folders too.
    case "$plugin_dir" in '~/'*) plugin_dir="$HOME/''${plugin_dir#\~/}" ;; esac
    mkdir -p "$plugin_dir"
    target="$plugin_dir/workmode.15s.sh"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
      echo "Refusing to overwrite existing plugin: $target" >&2
      exit 1
    fi
    ln -sfn ${plugin} "$target"
    # Moving an app bundle does not terminate its old running instance.
    # Retire only the former managed SwiftBar path before opening the new one.
    /usr/bin/pkill -TERM -f '^/Applications/Nix Apps/SwiftBar[.]app/Contents/MacOS/SwiftBar$' || true
    /usr/bin/open -g '/Applications/Nix Background Apps/SwiftBar.app'
    /run/current-system/sw/bin/workmode setup
  '';
in
{
  options.homelab.workmode.enable = lib.mkEnableOption "portable focus profiles with Abstand and SwiftBar";
  config = lib.mkIf cfg.enable {
    homelab.backgroundApps.packages = [
      abstand
      pkgs.swiftbar
    ];
    environment.systemPackages = [ cli ];
    # Materialize the profile as a store file with a runtime dependency; a path
    # into the flake source can otherwise leave a dangling /etc symlink.
    environment.etc."workmode/profiles.json".text = builtins.readFile ./profiles.json;
    # Gecko can leave web-content accessibility inactive after a browser launch.
    # Abstand reads that tree to identify sites; macOS Accessibility permission
    # alone does not ensure it is available. Keep it enabled while Workmode is on.
    system.defaults.CustomSystemPreferences."/Library/Preferences/org.mozilla.firefox".Preferences."accessibility.force_disabled" =
      {
        Value = -1;
        Status = "locked";
        Type = "number";
      };

    launchd.user.agents.workmode = {
      serviceConfig = {
        Label = "com.therealrishabh.workmode";
        ProgramArguments = [ "${login}" ];
        RunAtLoad = true;
        ProcessType = "Background";
        StandardOutPath = "/tmp/workmode-login.log";
        StandardErrorPath = "/tmp/workmode-login.err";
      };
    };
  };
}
