{
  stdenvNoCC,
  fetchurl,
  autoPatchelfHook,
  lib,
  target ? "linux-x64",
}:
let
  release = import ./release.nix;
  mac = target == "darwin-arm64";
in
stdenvNoCC.mkDerivation {
  pname = if mac then "antigravity-cli-darwin" else "antigravity-cli";
  inherit (release) version;
  src = fetchurl {
    url = if mac then release.macUrl else release.linuxUrl;
    hash = if mac then release.macHash else release.linuxHash;
  };
  # The archive holds a single top-level `antigravity` executable.
  unpackPhase = ''
    tar -xzf "$src" antigravity
  '';
  dontBuild = true;
  dontStrip = true;
  # Keep Google's Developer ID signature intact on the Mac binary.
  dontFixup = mac;
  nativeBuildInputs = lib.optionals (!mac) [ autoPatchelfHook ];
  installPhase = ''
    install -Dm755 antigravity "$out/bin/agy"
    echo '{"version":"${release.version}","target":"${target}"}' > "$out/antigravity-package.json"
  '';
  doInstallCheck = !mac;
  installCheckPhase = ''
    test "$(HOME="$TMPDIR" "$out/bin/agy" --version)" = "${release.version}"
  '';
}
