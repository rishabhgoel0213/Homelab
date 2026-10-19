{
  autoPatchelfHook,
  fd,
  fetchurl,
  lib,
  makeWrapper,
  ripgrep,
  stdenv,
}:

let
  version = "1.3.0";
in
stdenv.mkDerivation {
  pname = "pi-coding-agent";
  inherit version;

  src = fetchurl {
    url = "https://github.com/earendil-works/pi/releases/download/v${version}/pi-linux-x64.tar.gz";
    hash = "sha256-JPW+Motm1No2h2KWmJUBl09Dq4Q0+7V8NcUjo+pQXe0=";
  };

  sourceRoot = "pi";
  nativeBuildInputs = [
    autoPatchelfHook
    makeWrapper
  ];
  buildInputs = [ stdenv.cc.cc.lib ];

  dontBuild = true;
  dontAutoPatchelf = true;
  # Pi's executable is a self-contained binary with an embedded JavaScript
  # payload; stripping the ELF removes data needed at runtime.
  dontStrip = true;

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/bin" "$out/libexec"
    cp -R . "$out/libexec/pi"
    autoPatchelf "$out/libexec/pi/pi"
    makeWrapper "$out/libexec/pi/pi" "$out/bin/pi" \
      --prefix PATH : ${
        lib.makeBinPath [
          ripgrep
          fd
        ]
      }

    runHook postInstall
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    test "$("$out/bin/pi" --version)" = "${version}"
  '';

  meta = {
    description = "Coding agent CLI with read, bash, edit, write tools and session management";
    homepage = "https://pi.dev/";
    downloadPage = "https://github.com/earendil-works/pi/releases/tag/v${version}";
    license = lib.licenses.mit;
    mainProgram = "pi";
    platforms = [ "x86_64-linux" ];
  };
}
