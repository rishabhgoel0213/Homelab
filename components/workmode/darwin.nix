{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.homelab.workmode;
  profiles = builtins.fromJSON (builtins.readFile ./profiles.json);
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
  launchers = pkgs.runCommand "workmode-launchers" { } (
    lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: profile: ''
        app="$out/Applications/Workmode ${profile.label}.app"
        mkdir -p "$app/Contents/MacOS"
        cat > "$app/Contents/Info.plist" <<'PLIST'
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0"><dict>
        <key>CFBundleIdentifier</key><string>com.therealrishabh.workmode.${name}</string>
        <key>CFBundleName</key><string>Workmode ${profile.label}</string>
        <key>CFBundleExecutable</key><string>launch</string>
        <key>CFBundlePackageType</key><string>APPL</string>
        <key>CFBundleVersion</key><string>1</string>
        <key>LSUIElement</key><true/>
        </dict></plist>
        PLIST
        cat > "$app/Contents/MacOS/launch" <<'SCRIPT'
        #!/bin/sh
        export SWIFTBAR=1
        exec /run/current-system/sw/bin/workmode start ${lib.escapeShellArg name}
        SCRIPT
        chmod +x "$app/Contents/MacOS/launch"
      '') profiles.profiles
    )
  );
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
    environment.systemPackages = [
      cli
      launchers
    ];
    environment.etc."workmode/profiles.json".source = ./profiles.json;
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
