{
  config,
  inputs,
  lib,
  macbookArtifacts,
  pkgs,
  ...
}:

let
  cfg = config.homelab.apps.zen;
  sourcePackage = pkgs.callPackage ./package.nix {
    src = inputs.zen-browser;
  };
  selectedPackage = if cfg.packageSource == "source" then sourcePackage else macbookArtifacts.zen;
in
{
  options.homelab.apps.zen.packageSource = lib.mkOption {
    type = lib.types.enum [
      "prebuilt"
      "source"
    ];
    default = "prebuilt";
    description = "Whether to use the pinned upstream bundle or the managed source checkout.";
  };

  config.environment.systemPackages = [ selectedPackage ];
}
