# Prepared on Linux, executed on macOS. Preserve upstream Apple signatures.
{
  fetchurl,
  lib,
  python3,
  stdenvNoCC,
}:
let
  inherit (import ./release.nix) version macArchiveHash macTarget;
in
stdenvNoCC.mkDerivation {
  pname = "codex-darwin-bundle";
  inherit version;
  src = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rust-v${version}/codex-provisioned-package-${macTarget}.tar.gz";
    hash = macArchiveHash;
  };
  sourceRoot = "source";
  unpackPhase = ''
    mkdir source
    tar -xzf "$src" -C source
  '';
  dontBuild = true;
  # Mach-O contents must remain byte-for-byte signed by upstream.
  dontFixup = true;
  installPhase = ''
    mkdir -p "$out"
    cp -a ./. "$out/"
  '';
  doInstallCheck = true;
  nativeInstallCheckInputs = [ python3 ];
  installCheckPhase = ''
    python3 ${./tests/package.py} "$src" "$out" "${version}" "${macTarget}" --mac-archive
  '';
  meta = {
    description = "Complete upstream-signed Apple-silicon Codex CLI bundle";
    homepage = "https://github.com/openai/codex";
    license = lib.licenses.asl20;
    platforms = [ "x86_64-linux" ];
  };
}
