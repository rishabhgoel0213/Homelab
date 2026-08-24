{
  config,
  lib,
  macbookPackages,
  ...
}:

let
  cfg = config.homelab.apps.zen;
  selectedPackage =
    if cfg.packageSource == "source" then macbookPackages.zenSource else macbookPackages.zen;
in
{
  options.homelab.apps.zen.packageSource = lib.mkOption {
    type = lib.types.enum [
      "prebuilt"
      "source"
    ];
    default = "prebuilt";
    description = "Whether to use the pinned upstream bundle or the server-cross-compiled source bundle.";
  };

  config = {
    environment.systemPackages = [ selectedPackage ];

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
