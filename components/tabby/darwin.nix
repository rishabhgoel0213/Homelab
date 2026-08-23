{
  config,
  inputs,
  lib,
  macbookArtifacts,
  macbookPackages,
  pkgs,
  ...
}:

let
  cfg = config.homelab.apps.tabby;
  tabbyPlugins = macbookArtifacts.tabbyPlugins;
  sourcePackage = pkgs.callPackage ./package.nix {
    src = inputs.tabby-terminal;
    inherit tabbyPlugins;
  };
  selectedPackage = if cfg.packageSource == "source" then sourcePackage else macbookPackages.tabby;
in
{
  options.homelab.apps.tabby.packageSource = lib.mkOption {
    type = lib.types.enum [
      "prebuilt"
      "source"
    ];
    default = "prebuilt";
    description = "Whether to use the pinned upstream bundle or the managed source checkout.";
  };

  config = {
    environment.systemPackages = [ selectedPackage ];

    # Tabby supports an external plugin search path. Keeping plugins outside
    # the app preserves the upstream bundle and lets Linux build their locked
    # JavaScript dependency tree.
    launchd.user.envVariables.TABBY_PLUGINS = "${tabbyPlugins}/lib/tabby/plugins";
  };
}
