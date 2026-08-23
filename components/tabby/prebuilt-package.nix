{
  archive,
  lib,
  stdenvNoCC,
}:

let
  version = "1.0.235";
in
stdenvNoCC.mkDerivation {
  pname = "tabby-terminal-prebuilt";
  inherit version;
  dontUnpack = true;
  dontFixup = true;

  installPhase = ''
    runHook preInstall

    mkdir -p unpacked "$out/Applications"
    /usr/bin/ditto -x -k \
      "${archive}/share/tabby/tabby-${version}-macos-arm64.zip" \
      unpacked
    app="$(find unpacked -type d -name 'Tabby.app' -print -quit)"
    test -n "$app"
    /usr/bin/ditto --noextattr --noqtn \
      "$app" "$out/Applications/Tabby.app"
    /usr/bin/xattr -cr "$out/Applications/Tabby.app"
    /usr/bin/codesign --verify --deep --strict \
      "$out/Applications/Tabby.app"

    runHook postInstall
  '';

  meta = {
    description = "Pinned upstream Tabby Terminal bundle for Apple silicon";
    homepage = "https://tabby.sh";
    license = lib.licenses.mit;
    platforms = [ "aarch64-darwin" ];
  };
}
