{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.homelab.spaceWallpaper;
  python = pkgs.python3.withPackages (ps: [
    ps.pillow
  ]);
  cli = pkgs.writeShellScriptBin "space-wallpaper" ''
    export SPACE_WALLPAPER_CONFIG=/etc/space-wallpaper/config.json
    export SPACE_WALLPAPER_DESKTOP_HELPER=${./set-desktop.js}
    exec ${python}/bin/python3 ${./wallpaper.py} "$@"
  '';
  plugin = pkgs.writeShellScript "space-wallpaper.1m.sh" ''
    # <xbar.title>Space Wallpapers</xbar.title>
    # <xbar.desc>Discover the NASA image on your desktop</xbar.desc>
    # <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
    exec /run/current-system/sw/bin/space-wallpaper menu
  '';
  setup = pkgs.writeShellScript "space-wallpaper-menu-setup" ''
    set -eu
    plugin_dir=$(/usr/bin/defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)
    if [ -z "$plugin_dir" ]; then
      plugin_dir="$HOME/Library/Application Support/${
        if config.homelab.workmode.enable then "Workmode" else "Space Wallpapers"
      }/SwiftBar"
      /usr/bin/defaults write com.ameba.SwiftBar PluginDirectory -string "$plugin_dir"
    fi
    case "$plugin_dir" in '~/'*) plugin_dir="$HOME/''${plugin_dir#\~/}" ;; esac
    mkdir -p "$plugin_dir"
    target="$plugin_dir/space-wallpaper.1m.sh"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
      echo "Refusing to overwrite existing SwiftBar plugin: $target" >&2
      exit 1
    fi
    ln -sfn ${plugin} "$target"
    /usr/bin/open -g '/Applications/Nix Background Apps/SwiftBar.app'
  '';
in
{
  options.homelab.spaceWallpaper = {
    enable = lib.mkEnableOption "curated high-resolution NASA wallpaper rotation";
    intervalSeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 3600;
      description = "Minimum time between automatic wallpaper changes while logged in.";
    };
    cacheImages = lib.mkOption {
      type = lib.types.ints.between 2 50;
      default = 8;
      description = "Maximum number of locally retained images (8 MiB each at most).";
    };
    directory = lib.mkOption {
      type = lib.types.str;
      default = "~/Pictures/Space Wallpapers";
      description = "Local image cache; only this component's generated files are pruned.";
    };
  };
  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cli ];
    homelab.backgroundApps.packages = [ pkgs.swiftbar ];
    environment.etc."space-wallpaper/catalogue.json".text = builtins.readFile ./catalogue.json;
    environment.etc."space-wallpaper/config.json".text = builtins.toJSON {
      inherit (cfg) directory intervalSeconds cacheImages;
      catalogue = "/etc/space-wallpaper/catalogue.json";
      stateDirectory = "~/Library/Application Support/Space Wallpapers";
      maxDownloadMiB = 96;
      maxImageMiB = 8;
    };
    launchd.user.agents.space-wallpaper = {
      serviceConfig = {
        Label = "com.therealrishabh.space-wallpaper";
        ProgramArguments = [
          "${cli}/bin/space-wallpaper"
          "tick"
        ];
        RunAtLoad = true;
        # Retry failed downloads after five minutes; the CLI enforces the hour.
        StartInterval = 300;
        LimitLoadToSessionType = "Aqua";
        ProcessType = "Background";
        LowPriorityIO = true;
        StandardOutPath = "/tmp/space-wallpaper.log";
        StandardErrorPath = "/tmp/space-wallpaper.err";
      };
    };
    launchd.user.agents.space-wallpaper-menu = {
      serviceConfig = {
        Label = "com.therealrishabh.space-wallpaper-menu";
        ProgramArguments = [ "${setup}" ];
        RunAtLoad = true;
        LimitLoadToSessionType = "Aqua";
        ProcessType = "Background";
        StandardOutPath = "/tmp/space-wallpaper-menu.log";
        StandardErrorPath = "/tmp/space-wallpaper-menu.err";
      };
    };
  };
}
