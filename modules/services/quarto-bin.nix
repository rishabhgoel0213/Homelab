{
  lib,
  stdenv,
  fetchurl,
  autoPatchelfHook,
  makeWrapper,
  bash,
  coreutils,
  openssl,
  which,
  zlib,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "quarto-bin";
  version = "1.9.37";

  src = fetchurl {
    url = "https://github.com/quarto-dev/quarto-cli/releases/download/v${finalAttrs.version}/quarto-${finalAttrs.version}-linux-amd64.tar.gz";
    hash = "sha256-ePzZDpg+Pn2+Pw0ZIcwQJTweynuSwg3UvCo8G8oKmvU=";
  };

  nativeBuildInputs = [
    autoPatchelfHook
    makeWrapper
  ];
  buildInputs = [
    stdenv.cc.cc.lib
    openssl
    zlib
  ];

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    mkdir -p "$out"
    cp -R . "$out/"
    wrapProgram "$out/bin/quarto" \
      --prefix PATH : ${lib.makeBinPath [
        bash
        coreutils
        which
      ]}
    runHook postInstall
  '';

  meta = {
    description = "Official Quarto CLI bundle with matched rendering dependencies";
    homepage = "https://quarto.org/";
    license = lib.licenses.gpl2Plus;
    platforms = [ "x86_64-linux" ];
    mainProgram = "quarto";
  };
})
