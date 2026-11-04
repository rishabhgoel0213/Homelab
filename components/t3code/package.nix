{
  autoPatchelfHook,
  fetchurl,
  lib,
  makeWrapper,
  musl,
  stdenv,
}:

let
  version = "0.1.8-nightly.20261104.4192";
  mobileApkName = "t3code-android-internal-2.2.0-742.apk";
  mobileApkHash = "sha256-NEL7iX9+FeYDm2MERuwGl8oZR95REgvc0wvzeYkLqBM=";
in
stdenv.mkDerivation {
  pname = "t3code";
  inherit version;
  src = fetchurl {
    url = "https://github.com/pingdotgg/t3code/releases/download/v${version}/t3-${version}-linux-x64.tar.gz";
    hash = "sha256-JCavWwBXWAL4JdMIsCydySikI45XUf8D93CdsOeok5g=";
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
  passthru = {
    inherit mobileApkName mobileApkHash;
    mobileApk = fetchurl {
      url = "https://github.com/pingdotgg/t3code/releases/download/v${version}/${mobileApkName}";
      hash = mobileApkHash;
    };
  };
  meta = {
    description = "Official T3 Code nightly server and web UI";
    homepage = "https://github.com/pingdotgg/t3code";
    license = lib.licenses.mit;
    mainProgram = "t3";
    platforms = [ "x86_64-linux" ];
  };
}
