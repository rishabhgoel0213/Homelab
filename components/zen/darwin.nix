{
  lib,
  macbookPackages,
  pkgs,
  ...
}:

let
  selectedPackage = macbookPackages.zen;
  firefoxCli = macbookPackages.firefoxCli;
  nativeHostManifest = pkgs.writeText "firefox-cli-native-host.json" (
    builtins.toJSON {
      name = "firefox_cli";
      description = "Native messaging host for firefox-cli.";
      path = "${firefoxCli}/bin/firefox-cli";
      type = "stdio";
      allowed_extensions = [ "ff-cli-bridge@respawn.pro" ];
    }
  );
  devtoolsMcpPackage = pkgs.callPackage ./devtools-mcp/package.nix { };
  zenLiveDevtoolsMcp = pkgs.writeShellApplication {
    name = "zen-live-devtools-mcp";
    runtimeInputs = [
      devtoolsMcpPackage
      pkgs.geckodriver
    ];
    text = ''
      exec firefox-devtools-mcp \
        --connectExisting \
        --marionettePort 2828 \
        --toolPreset developer \
        "$@"
    '';
  };
  zenAutomation = pkgs.writeShellApplication {
    name = "zen-automation";
    text = ''
      exec ${lib.escapeShellArg "${selectedPackage}/Applications/Zen.app/Contents/MacOS/zen"} \
        --no-remote \
        --marionette \
        --remote-debugging-port \
        "$@"
    '';
  };
  zenFirefoxCliXpi = pkgs.writeShellScriptBin "zen-firefox-cli-xpi" ''
    printf '%s\n' ${lib.escapeShellArg "${firefoxCli}/share/firefox-cli/firefox-cli.xpi"}
  '';
in
{
  config = {
    environment.systemPackages = [
      selectedPackage
      firefoxCli
      zenAutomation
      zenFirefoxCliXpi
      zenLiveDevtoolsMcp
    ];

    system.activationScripts.postActivation.text = lib.mkAfter ''
      native_host_dir="/Users/rishabhgoel/Library/Application Support/Mozilla/NativeMessagingHosts"
      native_host_manifest="$native_host_dir/firefox_cli.json"
      install -d -m 0755 -o rishabhgoel -g staff "$native_host_dir"
      if [[ -e "$native_host_manifest" && ! -L "$native_host_manifest" ]]; then
        echo "Refusing to replace unmanaged Firefox CLI native host: $native_host_manifest" >&2
        exit 1
      fi
      ln -sfn ${nativeHostManifest} "$native_host_manifest"
      chown -h rishabhgoel:staff "$native_host_manifest"
    '';

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
