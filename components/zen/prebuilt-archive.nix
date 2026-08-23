{
  fetchurl,
  lib,
  stdenvNoCC,
}:

let
  version = "1.21.15b";
in
stdenvNoCC.mkDerivation {
  pname = "zen-browser-prebuilt-archive";
  inherit version;

  src = fetchurl {
    url = "https://github.com/zen-browser/desktop/releases/download/${version}/zen.macos-universal.dmg";
    hash = "sha256-Do6fOjbV80tTNWMeSVQU9G+Nj7eOe6WnMvmSMF3o4Ec=";
  };

  dontUnpack = true;
  dontFixup = true;

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/share/zen"
    cp "$src" "$out/share/zen/zen-${version}-macos-universal.dmg"

    runHook postInstall
  '';

  meta = {
    description = "Pinned upstream Zen Browser disk image for native macOS extraction";
    homepage = "https://zen-browser.app";
    license = lib.licenses.mpl20;
    platforms = lib.platforms.linux;
  };
}
