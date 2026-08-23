{
  archive,
  lib,
  stdenvNoCC,
}:

let
  version = "1.21.15b";
in
stdenvNoCC.mkDerivation {
  pname = "zen-browser-prebuilt";
  inherit version;

  dontUnpack = true;
  dontFixup = true;

  installPhase = ''
    runHook preInstall

    export HOME="$TMPDIR/home"
    mkdir -p "$HOME" mount "$out/Applications"

    mounted=0
    cleanup_mount() {
      if [[ "$mounted" -eq 1 ]]; then
        /usr/bin/hdiutil detach "$TMPDIR/mount" >/dev/null || true
      fi
    }
    trap cleanup_mount EXIT

    /usr/bin/hdiutil attach -nobrowse -readonly \
      -mountpoint "$TMPDIR/mount" \
      "${archive}/share/zen/zen-${version}-macos-universal.dmg" \
      >/dev/null
    mounted=1

    /usr/bin/ditto --noextattr --noqtn \
      "$TMPDIR/mount/Zen.app" "$out/Applications/Zen.app"
    /usr/bin/hdiutil detach "$TMPDIR/mount" >/dev/null
    mounted=0

    /usr/bin/xattr -cr "$out/Applications/Zen.app"
    /usr/bin/codesign --verify --deep --strict \
      "$out/Applications/Zen.app"

    runHook postInstall
  '';

  meta = {
    description = "Pinned upstream Zen Browser bundle with its vendor signature preserved";
    homepage = "https://zen-browser.app";
    license = lib.licenses.mpl20;
    platforms = [ "aarch64-darwin" ];
  };
}
