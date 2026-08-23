{
  fetchurl,
  lib,
  rcodesign,
  stdenvNoCC,
  unzip,
}:

let
  version = "1.0.235";
in
stdenvNoCC.mkDerivation {
  pname = "tabby-terminal-prebuilt";
  inherit version;

  src = fetchurl {
    url = "https://github.com/Eugeny/tabby/releases/download/v${version}/tabby-${version}-macos-arm64.zip";
    hash = "sha256-EICgXUTIrP6TAexWxf+jqw5HIIbRrOj+il4sv59xx9U=";
  };

  nativeBuildInputs = [
    rcodesign
    unzip
  ];
  dontUnpack = true;
  dontFixup = true;

  installPhase = ''
    runHook preInstall

    mkdir -p unpacked "$out/Applications"
    unzip -q "$src" -d unpacked
    app="$(find unpacked -type d -name 'Tabby.app' -print -quit)"
    test -n "$app"
    cp -a "$app" "$out/Applications/Tabby.app"
    chmod -R u+w "$out/Applications/Tabby.app"

    # The upstream 1.0.235 ZIP carries a Developer ID signature that Apple's
    # verifier reports as modified. Re-sign the otherwise untouched bundle ad
    # hoc so the staged and installed Nix artifact has a valid code envelope.
    rcodesign sign "$out/Applications/Tabby.app"

    runHook postInstall
  '';

  meta = {
    description = "Pinned upstream Tabby Terminal bundle for Apple silicon";
    homepage = "https://tabby.sh";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
  };
}
