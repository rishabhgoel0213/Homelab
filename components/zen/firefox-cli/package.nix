{
  archive,
  lib,
  stdenvNoCC,
}:

let
  version = "0.3.0";
in
stdenvNoCC.mkDerivation {
  pname = "firefox-cli-macos";
  inherit version;

  dontUnpack = true;
  dontFixup = true;
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/bin" "$out/share/firefox-cli" "$TMPDIR/firefox-cli"
    /usr/bin/tar -xzf \
      "${archive}/share/firefox-cli/firefox-cli-${version}-macos-arm64.tar.gz" \
      -C "$TMPDIR/firefox-cli"
    cp "$TMPDIR/firefox-cli/package/bin/darwin-arm64/firefox-cli" "$out/bin/firefox-cli"
    cp "$TMPDIR/firefox-cli/extension-artifacts/firefox-cli-${version}.xpi" \
      "$out/share/firefox-cli/firefox-cli.xpi"
    chmod 0755 "$out/bin/firefox-cli"
    runHook postInstall
  '';

  meta = {
    description = "Firefox CLI for the user's existing Zen tabs and sessions";
    homepage = "https://github.com/respawn-llc/firefox-cli";
    license = lib.licenses.agpl3Only;
    platforms = [ "aarch64-darwin" ];
    mainProgram = "firefox-cli";
  };
}
