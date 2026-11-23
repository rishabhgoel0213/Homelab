{
  autoPatchelfHook,
  fetchurl,
  lib,
  makeWrapper,
  musl,
  stdenv,
  target ? "linux-x64",
}:

let
  version = "0.1.8-nightly.20261105.4218";
  linuxHash = "sha256-sgZfU1I/dzNMTg7qr7mw0iPEsC7DuRbF+z6eHHeMzMw=";
  macHash = "sha256-fSozhW5V1Xb8QfJne0Fd18OuBRHejAbzn7yglOAZZ+I=";
  mobileApkName = "t3code-android-internal-2.2.0-743.apk";
  mobileApkHash = "sha256-9DxUOUlgP8a2nMjcu+5/0g/tLP097WtmT/TKjmBO4CY=";
  mac = target == "darwin-arm64";
in
stdenv.mkDerivation {
  pname = if mac then "t3code-darwin" else "t3code";
  inherit version;
  src = fetchurl {
    url = "https://github.com/pingdotgg/t3code/releases/download/v${version}/t3-${version}-${target}.tar.gz";
    hash = if mac then macHash else linuxHash;
  };
  nativeBuildInputs = lib.optionals (!mac) [
    autoPatchelfHook
    makeWrapper
  ];
  buildInputs = lib.optionals (!mac) [
    stdenv.cc.cc.lib
    musl
  ];
  dontBuild = true;
  dontAutoPatchelf = true;
  # The Bun executable contains its bundled JavaScript payload and macOS code signature.
  dontStrip = true;
  dontFixup = mac;
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/bin" "$out/libexec/t3code"
    cp -R . "$out/libexec/t3code/"
    ${
      if mac then
        ''
          chmod -R a+rX "$out/libexec/t3code"
          ln -s ../libexec/t3code/t3 "$out/bin/t3"
          ln -s t3 "$out/bin/t3code"
          echo '{"version":"${version}","target":"${target}"}' > "$out/t3code-package.json"
        ''
      else
        ''
          autoPatchelf "$out/libexec/t3code"
          makeWrapper "$out/libexec/t3code/t3" "$out/bin/t3"
          ln -s t3 "$out/bin/t3code"
        ''
    }
    runHook postInstall
  '';
  doInstallCheck = !mac;
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
    platforms = [
      "x86_64-linux"
      "aarch64-darwin"
    ];
  };
}
