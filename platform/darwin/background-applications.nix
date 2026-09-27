{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.homelab.backgroundApps;
  applications = pkgs.buildEnv {
    name = "background-applications";
    paths = cfg.packages;
    pathsToLink = [ "/Applications" ];
  };
in
{
  options.homelab.backgroundApps.packages = lib.mkOption {
    type = lib.types.listOf lib.types.package;
    default = [ ];
    description = "Background app bundles installed in /Applications/Nix Background Apps instead of the Dock-facing Nix Apps folder.";
  };
  config = lib.mkIf (cfg.packages != [ ]) {
    # Copy these first: the normal application activation then removes their old
    # copies from Nix Apps. Keep real signed bundles, matching nix-darwin's app
    # installer, rather than exposing symlinks into the store to LaunchServices.
    system.activationScripts.applications.text = lib.mkBefore ''
      echo "setting up /Applications/Nix Background Apps..." >&2
      backgroundFolder='/Applications/Nix Background Apps'
      mkdir -p "$backgroundFolder"
      ${lib.getExe pkgs.rsync} \
        --checksum --copy-unsafe-links --archive --delete \
        --chmod=-w --no-group --no-owner \
        ${applications}/Applications/ "$backgroundFolder"
    '';
  };
}
