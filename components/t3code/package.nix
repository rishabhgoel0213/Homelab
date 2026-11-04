{
  autoPatchelfHook,
  fetchurl,
  lib,
  makeWrapper,
  musl,
  stdenv,
}:

let
  version = "0.1.8-nightly.20261104.4179";
in
stdenv.mkDerivation {
  pname = "t3code";
  inherit version;
  src = fetchurl {
    url = "https://github.com/pingdotgg/t3code/releases/download/v${version}/t3-${version}-linux-x64.tar.gz";
    hash = "sha256-hOFi1kq/l1qmutRnOxlXpbu2+1zV2io9CzcjcGHlEb4=";
  };
  nativeBuildInputs = [
    autoPatchelfHook
    makeWrapper
  ];
  buildInputs = [
    stdenv.cc.cc.lib
    musl
  ];
  dontBuild = true;
  dontAutoPatchelf = true;
  # The Bun executable contains its bundled JavaScript payload.
  dontStrip = true;
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/bin" "$out/libexec/t3code"
    cp -R . "$out/libexec/t3code/"
    autoPatchelf "$out/libexec/t3code"
    makeWrapper "$out/libexec/t3code/t3" "$out/bin/t3"
    ln -s t3 "$out/bin/t3code"
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    test "$("$out/bin/t3" --version)" = "t3 v${version}"
  '';
  meta = {
    description = "Official T3 Code nightly server and web UI";
    homepage = "https://github.com/pingdotgg/t3code";
    license = lib.licenses.mit;
    mainProgram = "t3";
    platforms = [ "x86_64-linux" ];
  };
}
