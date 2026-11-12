{ buildNpmPackage, lib, autoPatchelfHook, stdenv, nodejs, makeWrapper, t3Package }:
let
  manifest = builtins.fromJSON (builtins.readFile ./package.json);
in
buildNpmPackage {
  pname = "t3code-device-tools";
  version = manifest.version;
  src = lib.cleanSource ./.;
  npmDepsHash = "sha256-dhwLXJaDfPPS0js6y66SwNAvNnirt4q4zx/J59nX+fU=";
  dontNpmBuild = true;
  nativeBuildInputs = [ autoPatchelfHook makeWrapper ];
  buildInputs = [ stdenv.cc.cc.lib ];
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib" "$out/bin"
    cp -R node_modules "$out/lib/"
    for spec in agent-device:${manifest.dependencies.agent-device} expo-device-hub:${manifest.dependencies.expo-device-hub}; do
      name="''${spec%:*}"
      version="''${spec#*:}"
      # Fail an upstream nightly update rather than silently install mismatched helpers.
      grep -aF '"'"$name"'": "'"$version"'"' ${t3Package}/libexec/t3code/t3 >/dev/null
      mkdir -p "$out/tools/$name/$version"
      ln -s "$out/lib/node_modules" "$out/tools/$name/$version/node_modules"
      printf '%s\n' "$version" > "$out/tools/$name/$version/.install-complete"
    done
    makeWrapper ${nodejs}/bin/node "$out/bin/agent-device" \
      --add-flags "$out/lib/node_modules/agent-device/bin/agent-device.mjs"
    makeWrapper ${nodejs}/bin/node "$out/bin/expo-device-hub" \
      --add-flags "$out/lib/node_modules/expo-device-hub/dist/server/cli.mjs"
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    "$out/bin/agent-device" --version
    "$out/bin/expo-device-hub" --help
    ${nodejs}/bin/node --input-type=module -e "await import('$out/lib/node_modules/node-datachannel/dist/esm/lib/index.mjs')"
  '';
}
