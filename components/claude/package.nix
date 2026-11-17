{
  stdenvNoCC,
  fetchurl,
  autoPatchelfHook,
  gcc,
  lib,
  target ? "linux-x64",
}:
let
  release = import ./release.nix;
  mac = target == "darwin-arm64";
in
stdenvNoCC.mkDerivation {
  pname = if mac then "claude-code-darwin" else "claude-code";
  inherit (release) version;
  src = fetchurl {
    url = "https://downloads.claude.ai/claude-code-releases/${release.version}/${target}/claude";
    hash = if mac then release.macHash else release.linuxHash;
  };
  dontUnpack = true;
  dontBuild = true;
  dontStrip = true;
  dontFixup = mac;
  nativeBuildInputs = lib.optionals (!mac) [ autoPatchelfHook ];
  buildInputs = lib.optionals (!mac) [ gcc.cc.lib ];
  installPhase = ''
    install -Dm755 "$src" "$out/bin/claude"
    echo '{"version":"${release.version}","target":"${target}"}' > "$out/claude-package.json"
  '';
}
