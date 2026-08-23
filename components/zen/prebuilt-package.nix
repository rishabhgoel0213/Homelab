{
  fetchurl,
  lib,
  p7zip,
  rcodesign,
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
  pname = "zen-browser-prebuilt";
  inherit version;

  src = fetchurl {
    url = "https://github.com/zen-browser/desktop/releases/download/${version}/zen.macos-universal.dmg";
    hash = "sha256-Do6fOjbV80tTNWMeSVQU9G+Nj7eOe6WnMvmSMF3o4Ec=";
  };

  nativeBuildInputs = [
    p7zip
    rcodesign
  ];
  dontUnpack = true;
  dontFixup = true;

  installPhase = ''
    runHook preInstall

    mkdir -p unpacked
    7z x -y "$src" -ounpacked >/dev/null
    app="$(find unpacked -type d -name 'Zen.app' -print -quit)"
    test -n "$app"
    mkdir -p "$out/Applications"
    cp -a "$app" "$out/Applications/Zen.app"
    chmod -R u+w "$out/Applications/Zen.app"
    mkdir -p "$out/Applications/Zen.app/Contents/Resources/distribution"
    printf '%s\n' ${lib.escapeShellArg policies} \
      > "$out/Applications/Zen.app/Contents/Resources/distribution/policies.json"

    # Adding enterprise policy changes the signed resource envelope. Re-sign
    # the otherwise upstream-prebuilt bundle ad hoc on the Linux build host.
    rcodesign sign "$out/Applications/Zen.app"

    runHook postInstall
  '';

  meta = {
    description = "Pinned upstream Zen Browser bundle with managed policy";
    homepage = "https://zen-browser.app";
    license = lib.licenses.mpl20;
    platforms = [ "x86_64-linux" ];
  };
}
