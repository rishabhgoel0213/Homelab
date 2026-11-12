{ buildNpmPackage, lib, autoPatchelfHook, stdenv, nodejs, makeWrapper, python3, t3Package ? null, fetchurl, iosOnly ? false }:
let
  manifest = builtins.fromJSON (builtins.readFile ./package.json);
  scrcpyServer = fetchurl {
    url = "https://github.com/Genymobile/scrcpy/releases/download/v4.0/scrcpy-server-v4.0";
    hash = "sha256-hJJL1WSh62CJyHLHUh+WgFiXf5H1/wJRSox0r/MhDzo=";
  };
in
buildNpmPackage {
  pname = "t3code-device-tools";
  version = manifest.version;
  src = lib.cleanSource ./.;
  npmDepsHash = "sha256-dhwLXJaDfPPS0js6y66SwNAvNnirt4q4zx/J59nX+fU=";
  dontNpmBuild = true;
  nativeBuildInputs = [ makeWrapper ] ++ lib.optional stdenv.hostPlatform.isLinux autoPatchelfHook;
  buildInputs = [ stdenv.cc.cc.lib ];
  # Preserve upstream signatures on the bundled Apple helpers.
  dontStrip = stdenv.hostPlatform.isDarwin;
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/lib" "$out/bin"
    cp -R node_modules "$out/lib/"
    ${lib.optionalString iosOnly ''
      # T3 invokes this entrypoint directly, bypassing our executable wrapper.
      # The dedicated Mac host must not infer a complete Android SDK from adb.
      hub="$out/lib/node_modules/expo-device-hub"
      substituteInPlace "$hub/dist/server/cli.mjs" \
        --replace-fail 'platform: { type: "string" },' 'platform: { type: "string", default: "ios" },'
      # T3 cannot open a device absent from discovery. Include newly provisioned
      # simulators before their first boot instead of requiring usage history.
      substituteInPlace "$hub/dist/server/index.mjs" \
        --replace-fail '    }).filter((device) => device.lastUsedAt !== undefined),' '    }),'
    ''}
    # The gRPC capture backend also starts scrcpy for input. Its lazy download
    # targets the package directory, which is immutable after installation.
    emu="$out/lib/node_modules/expo-device-hub/vendor/serve-emu"
    grep -F 'SCRCPY_VERSION = "4.0"' "$emu/dist/scrcpy-server.js"
    mkdir -p "$emu/vendor"
    ln -s ${scrcpyServer} "$emu/vendor/scrcpy-server-v4.0"
    for spec in agent-device:${manifest.dependencies.agent-device} expo-device-hub:${manifest.dependencies.expo-device-hub}; do
      name="''${spec%:*}"
      version="''${spec#*:}"
      # Fail an upstream nightly update rather than silently install mismatched helpers.
      ${lib.optionalString (t3Package != null) ''
        grep -aF '"'"$name"'": "'"$version"'"' ${t3Package}/libexec/t3code/t3 >/dev/null
      ''}
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
    ${nodejs}/bin/node --input-type=module -e "globalThis.fetch = () => { throw Error('unexpected runtime download'); }; const m = await import('$out/lib/node_modules/expo-device-hub/vendor/serve-emu/dist/scrcpy-server.js'); await m.ensureScrcpyServer();"
    ${lib.optionalString iosOnly ''
      ${python3}/bin/python ${./test-ios-discovery.py} ${nodejs}/bin/node "$out/lib/node_modules/expo-device-hub/dist/server/cli.mjs"
    ''}
  '';
}
