{
  alsa-lib,
  autoPatchelfHook,
  fetchurl,
  lib,
  ncurses,
  stdenv,
  stdenvNoCC,
  python3,
}:

let
  inherit (import ./release.nix) version archiveHash target;
in
stdenvNoCC.mkDerivation {
  pname = "codex";
  inherit version;

  # The full release package is the authority for binaries AND resources.
  # Do not enumerate Cargo targets or selectively copy known bundles here.
  src = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rust-v${version}/codex-package-${target}.tar.gz";
    hash = archiveHash;
  };
  sourceRoot = "source";
  unpackPhase = ''
    runHook preUnpack
    mkdir source
    tar -xzf "$src" -C source
    runHook postUnpack
  '';
  dontBuild = true;
  dontStrip = true;
  nativeBuildInputs = [ autoPatchelfHook ];
  buildInputs = [
    alsa-lib
    ncurses
    stdenv.cc.cc.lib
  ];

  installPhase = ''
    runHook preInstall
    mkdir -p "$out"
    cp -a ./. "$out/"
    runHook postInstall
  '';

  # Recursively fix every ELF, including future bundles. Missing dependencies
  # must fail the build instead of producing a partially working installation.
  doInstallCheck = true;
  nativeInstallCheckInputs = [ python3 ];
  installCheckPhase = ''
    runHook preInstallCheck
    python3 ${./tests/package.py} "$src" "$out" "${version}" "${target}"
    runHook postInstallCheck
  '';

  meta = {
    description = "Codex CLI with the complete upstream resource bundle";
    homepage = "https://github.com/openai/codex";
    license = lib.licenses.asl20;
    mainProgram = "codex";
    platforms = [ "x86_64-linux" ];
  };
}
