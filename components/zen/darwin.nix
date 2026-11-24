{
  lib,
  macbookPackages,
  pkgs,
  ...
}:

let
  selectedPackage = macbookPackages.zen;
  zenSpaceRouterExtension = pkgs.callPackage ./space-router/package.nix { };
  zenSpaceRouterXpi = pkgs.writeShellScriptBin "zen-space-router-xpi" ''
    printf '%s\n' ${lib.escapeShellArg "${zenSpaceRouterExtension}/share/zen-space-router/zen-space-router.xpi"}
  '';
in
{
  config = {
    environment.systemPackages = [
      selectedPackage
      zenSpaceRouterXpi
    ];

    system.activationScripts.postActivation.text = lib.mkAfter ''
      native_host_manifest="/Users/rishabhgoel/Library/Application Support/Mozilla/NativeMessagingHosts/firefox_cli.json"
      if [[ -L "$native_host_manifest" ]]; then
        target="$(readlink "$native_host_manifest" || true)"
        if [[ "$target" == /nix/store/*firefox-cli* ]]; then
          rm -f "$native_host_manifest"
        fi
      fi
    '';

    # Gecko's macOS enterprise policy reader queries NSUserDefaults for the
    # app's own CFBundleIdentifier (app.zen-browser.zen), keeping policy
    # outside Zen.app so the vendor signature remains intact.
    system.defaults.CustomSystemPreferences."/Library/Preferences/app.zen-browser.zen" = {
      EnterprisePoliciesEnabled = true;
      DisableAppUpdate = true;
      Preferences = {
        "extensions.experiments.enabled" = {
          Value = true;
          Status = "default";
          Type = "boolean";
        };
        "xpinstall.signatures.required" = {
          Value = false;
          Status = "default";
          Type = "boolean";
        };
      };
      ExtensionSettings = {
        "*".installation_mode = "allowed";
        "{446900e4-71c2-419f-a6a7-df9c091e268b}" = {
          installation_mode = "force_installed";
          install_url = "https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi";
        };
        "zen-space-router@homelab.internal" = {
          installation_mode = "force_installed";
          install_url = "file://${zenSpaceRouterExtension}/share/zen-space-router/zen-space-router.xpi";
          default_area = "navbar";
        };
      };
    };
  };
}
