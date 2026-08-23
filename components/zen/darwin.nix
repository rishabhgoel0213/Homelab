{
  config,
  inputs,
  lib,
  pkgs,
  self,
  ...
}:

let
  cfg = config.homelab.apps.zen;
  sourcePackage = pkgs.callPackage ./package.nix {
    src = inputs.zen-browser;
  };
  selectedPackage =
    if cfg.packageSource == "source" then sourcePackage else self.packages.x86_64-linux.macbook-zen;
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
