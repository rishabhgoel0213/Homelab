{
  lib,
  stdenvNoCC,
  fetchurl,
}:
stdenvNoCC.mkDerivation {
  pname = "abstand";
  version = "0.1.35";
  src = fetchurl {
    url = "https://github.com/builder-group/abstand/releases/download/v0.1.35/Abstand_aarch64.app.tar.gz";
    sha256 = "353e6f3e9c35590a512d2929efa2244ff9ce161d16b570803d422534f6ce3ffe";
  };
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
