{
  lib,
  pkgs,
  presetName,
  displayName,
  bundleIdentifier,
  dataRoot,
  icon ? null,
  extensions ? [ ],
  settings ? { },
  workspace ? null,
  remoteHost ? null,
  remotePath ? null,
  localPathPrefix ? null,
  mutableExtensions ? false,
  appVersion ? "1.0",
}:

let
  iconFile =
    if icon == null then
      "${pkgs.vscodium}/Applications/VSCodium.app/Contents/Resources/VSCodium.icns"
    else
      icon;

  extensionJsonFile = pkgs.writeTextFile {
    name = "vscodium-${presetName}-extensions-json";
    destination = "/share/vscode/extensions/extensions.json";
    text = pkgs.vscode-utils.toExtensionJson extensions;
  };

  managedExtensionDir = pkgs.buildEnv {
    name = "vscodium-${presetName}-extensions";
    paths = extensions ++ [ extensionJsonFile ];
  };

  extensionDir =
    if mutableExtensions then
      "${dataRoot}/extensions"
    else
      "${managedExtensionDir}/share/vscode/extensions";

  settingsFile = pkgs.writeText "vscodium-${presetName}-settings.json" (builtins.toJSON settings);

  codium = pkgs.writeShellScriptBin "codium-${presetName}" ''
    set -eu
    mkdir -p ${lib.escapeShellArg dataRoot}
    ${lib.optionalString mutableExtensions "mkdir -p ${lib.escapeShellArg extensionDir}"}
    exec ${pkgs.vscodium}/bin/codium \
      --extensions-dir ${lib.escapeShellArg extensionDir} \
      --user-data-dir ${lib.escapeShellArg dataRoot} \
      "$@"
  '';

  opener = pkgs.writeShellScriptBin "vscodium-open-${presetName}" ''
    set -eu
    ${
      if workspace == null then
        if remoteHost == null then
          ''
            exec ${codium}/bin/codium-${presetName} --new-window "$@"
          ''
        else
          ''
            remote_root=${lib.escapeShellArg remotePath}
            local_prefix=${lib.escapeShellArg (if localPathPrefix == null then "" else localPathPrefix)}
            remote_paths=()

            if [[ "$#" -eq 0 ]]; then
              remote_paths+=("$remote_root")
            else
              for requested_path in "$@"; do
                if [[ -n "$local_prefix" && "$requested_path" == "$local_prefix" ]]; then
                  remote_paths+=("$remote_root")
                elif [[ -n "$local_prefix" && "$requested_path" == "$local_prefix/"* ]]; then
                  relative_path="''${requested_path#"$local_prefix"/}"
                  remote_paths+=("$remote_root/$relative_path")
                else
                  remote_paths+=("$requested_path")
                fi
              done
            fi

            exec ${codium}/bin/codium-${presetName} \
              --new-window \
              --remote ${lib.escapeShellArg "ssh-remote+${remoteHost}"} \
              "''${remote_paths[@]}"
          ''
      else
        ''
          exec ${codium}/bin/codium-${presetName} \
            --new-window \
            ${lib.escapeShellArg (toString workspace)}
        ''
    }
  '';

  cli = pkgs.symlinkJoin {
    name = "vscodium-${presetName}-cli";
    paths = [
      codium
      opener
    ];
  };

  executableName = "VSCodium-${presetName}";
  infoPlist = pkgs.writeText "vscodium-${presetName}-Info.plist" ''
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
      <key>CFBundleDisplayName</key>
      <string>${lib.escapeXML displayName}</string>
      <key>CFBundleExecutable</key>
      <string>${executableName}</string>
      <key>CFBundleIconFile</key>
      <string>VSCodium.icns</string>
      <key>CFBundleIdentifier</key>
      <string>${lib.escapeXML bundleIdentifier}</string>
      <key>CFBundleName</key>
      <string>${lib.escapeXML displayName}</string>
      <key>CFBundlePackageType</key>
      <string>APPL</string>
      <key>CFBundleShortVersionString</key>
      <string>${lib.escapeXML appVersion}</string>
      <key>CFBundleVersion</key>
      <string>${lib.escapeXML appVersion}</string>
      <key>LSMinimumSystemVersion</key>
      <string>14.0</string>
      <key>NSHighResolutionCapable</key>
      <true/>
    </dict>
    </plist>
  '';

  launcher = pkgs.writeShellScript executableName ''
    set -eu
    exec ${cli}/bin/vscodium-open-${presetName} "$@"
  '';

  app = pkgs.runCommand "vscodium-${presetName}-app-${appVersion}" { } ''
    app="$out/Applications/${displayName}.app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    cp ${infoPlist} "$app/Contents/Info.plist"
    cp ${launcher} "$app/Contents/MacOS/${executableName}"
    chmod 0755 "$app/Contents/MacOS/${executableName}"
    cp ${iconFile} "$app/Contents/Resources/VSCodium.icns"
  '';
in
{
  inherit
    app
    cli
    codium
    extensionDir
    iconFile
    managedExtensionDir
    settingsFile
    ;
}
