{
  fetchurl,
  lib,
  stdenvNoCC,
}:

let
  version = "1.0.235";
in
stdenvNoCC.mkDerivation {
  pname = "tabby-terminal-prebuilt-archive";
  inherit version;

  src = fetchurl {
    url = "https://github.com/Eugeny/tabby/releases/download/v${version}/tabby-${version}-macos-arm64.zip";
    hash = "sha256-EICgXUTIrP6TAexWxf+jqw5HIIbRrOj+il4sv59xx9U=";
  };

  dontUnpack = true;
  dontFixup = true;

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/share/tabby"
    cp "$src" "$out/share/tabby/tabby-${version}-macos-arm64.zip"

    runHook postInstall
  '';

  meta = {
    description = "Pinned upstream Tabby Terminal archive for native macOS extraction";
    homepage = "https://tabby.sh";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
  };
}
