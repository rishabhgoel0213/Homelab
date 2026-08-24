{
  archive,
  lib,
  stdenvNoCC,
}:

let
  version = "1.21.15b";
  policies = builtins.toJSON {
    policies = {
      DisableAppUpdate = true;
      ExtensionSettings = {
        "*" = {
          installation_mode = "allowed";
        };
        "{446900e4-71c2-419f-a6a7-df9c091e268b}" = {
          installation_mode = "force_installed";
          install_url = "https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi";
        };
      };
    };
  };
in
stdenvNoCC.mkDerivation {
  pname = "zen-browser-source";
  inherit version;

  dontUnpack = true;
  dontFixup = true;

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/Applications"
    /usr/bin/ditto --noextattr --noqtn \
      "${archive}/Applications/Zen.app" "$out/Applications/Zen.app"

    mkdir -p "$out/Applications/Zen.app/Contents/Resources/distribution"
    printf '%s\n' ${lib.escapeShellArg policies} \
      > "$out/Applications/Zen.app/Contents/Resources/distribution/policies.json"

    /usr/bin/xattr -cr "$out/Applications/Zen.app"
    /usr/bin/codesign --force --deep --sign - --timestamp=none \
      "$out/Applications/Zen.app"
    /usr/bin/codesign --verify --deep --strict \
      "$out/Applications/Zen.app"

    runHook postInstall
  '';

  meta = {
    description = "Linux-cross-compiled Zen Browser, ad-hoc signed on macOS";
    homepage = "https://zen-browser.app";
    license = lib.licenses.mpl20;
    platforms = [ "aarch64-darwin" ];
  };
}
