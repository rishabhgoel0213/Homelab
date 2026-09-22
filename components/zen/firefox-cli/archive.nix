{
  fetchurl,
  lib,
  stdenvNoCC,
}:

let
  version = "0.3.0";
in
stdenvNoCC.mkDerivation {
  pname = "firefox-cli-macos-archive";
  inherit version;

  src = fetchurl {
    url = "https://github.com/respawn-llc/firefox-cli/releases/download/v${version}/firefox-cli-v${version}-macOS-ARM64.tar.gz";
    hash = "sha256-ko71Q56WQmmTvoZGBJc3JWiOEdRVyZspD7pGW9wQeOo=";
  };

  dontUnpack = true;
  dontFixup = true;
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/share/firefox-cli"
    cp "$src" "$out/share/firefox-cli/firefox-cli-${version}-macos-arm64.tar.gz"
    runHook postInstall
  '';

  meta = {
    description = "Pinned Firefox CLI and signed Firefox extension for Apple Silicon";
    homepage = "https://github.com/respawn-llc/firefox-cli";
    license = lib.licenses.agpl3Only;
    platforms = lib.platforms.linux;
  };
}
