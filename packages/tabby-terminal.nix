{
  electron_38,
  fetchYarnDeps,
  findutils,
  fixup-yarn-lock,
  lib,
  makeWrapper,
  nodejs_22,
  python3,
  runCommandLocal,
  src,
  stdenv,
  tabbyPlugins,
  yarn,
}:

let
  version = "1.0.235";
  electron = electron_38;

  # Tabby keeps independent lockfiles for the shell and every built-in plugin.
  # Combining them gives every nested `yarn install` one fixed offline mirror.
  combinedYarnLock =
    runCommandLocal "tabby-${version}-combined-yarn.lock" { nativeBuildInputs = [ findutils ]; }
      ''
        find ${src} -name yarn.lock -not -path '*/node_modules/*' -print0 \
          | sort -z \
          | xargs -0 cat > "$out"
      '';

  offlineCache = fetchYarnDeps {
    yarnLock = combinedYarnLock;
    hash = "sha256-kvwKmqh8+emkoiTeBoDCVqA9SjPGHpSOI2WSSl1vah4=";
  };
in
stdenv.mkDerivation {
  pname = "tabby-terminal";
  inherit version src;

  nativeBuildInputs = [
    fixup-yarn-lock
    makeWrapper
    nodejs_22
    python3
    yarn
  ];

  postPatch = ''
    substituteInPlace scripts/vars.mjs \
      --replace-fail \
        "export let version = childProcess.execSync('git describe --tags', { encoding:'utf-8' })" \
        "export let version = 'v${version}'"

    substituteInPlace scripts/build-macos.mjs \
      --replace-fail "mac: ['dmg', 'zip']," "mac: ['dir']," \
      --replace-fail "config: {" "config: { electronDist: process.env.ELECTRON_DIST, electronVersion: process.env.ELECTRON_VERSION,"
  '';

  configurePhase = ''
    runHook preConfigure

    export HOME="$TMPDIR/home"
    mkdir -p "$HOME"
    export npm_config_nodedir=${electron.headers}
    export ELECTRON_OVERRIDE_DIST_PATH=${electron.dist}
    yarn config set yarn-offline-mirror ${offlineCache}
    yarn config set offline true
    yarn config set disable-self-update-check true

    while IFS= read -r -d $'\0' lock; do
      fixup-yarn-lock "$lock"
    done < <(find . -name yarn.lock -not -path '*/node_modules/*' -print0)

    yarn install --offline --frozen-lockfile --non-interactive --no-progress

    runHook postConfigure
  '';

  buildPhase = ''
    runHook preBuild

    export ARCH=arm64
    export CI=1
    export CSC_IDENTITY_AUTO_DISCOVERY=false
    export ELECTRON_DIST=${electron.dist}
    export ELECTRON_VERSION=${electron.version}
    yarn build
    node scripts/prepackage-plugins.mjs
    node scripts/build-macos.mjs

    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall

    app="$(find dist -type d -name 'Tabby.app' -print -quit)"
    test -n "$app"
    mkdir -p "$out/Applications"
    cp -R "$app" "$out/Applications/Tabby.app"
    wrapProgram "$out/Applications/Tabby.app/Contents/MacOS/Tabby" \
      --set TABBY_PLUGINS ${tabbyPlugins}/lib/tabby/plugins
    /usr/bin/codesign --force --deep --sign - --timestamp=none "$out/Applications/Tabby.app"

    runHook postInstall
  '';

  meta = {
    description = "Tabby Terminal built from the managed server source checkout";
    homepage = "https://github.com/Eugeny/tabby";
    license = lib.licenses.mit;
    platforms = [ "aarch64-darwin" ];
  };
}
