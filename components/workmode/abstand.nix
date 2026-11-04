{
  lib,
  stdenvNoCC,
  archive,
}:
stdenvNoCC.mkDerivation {
  pname = "abstand";
  version = "0.1.35-brick.1";
  src = archive;
  dontUnpack = true;
  dontFixup = true;
  installPhase = ''
    mkdir -p "$out/Applications"
    tar -xzf "$src" -C "$out/Applications"
    test -x "$out/Applications/Abstand.app/Contents/MacOS/Abstand"
    /usr/bin/codesign --verify --deep --strict "$out/Applications/Abstand.app"
  '';
  meta = {
    description = "Open-source app and website blocker";
    homepage = "https://abstand.app";
    license = lib.licenses.agpl3Only;
    platforms = [ "aarch64-darwin" ];
  };
}
