{
  buildNpmPackage,
  cairo,
  cargo,
  clang,
  cmake,
  fetchzip,
  git,
  gnumake,
  gnutar,
  lib,
  mercurial,
  nasm,
  ninja,
  nodejs_22,
  pkg-config,
  python311,
  rust-cbindgen,
  rustPlatform,
  rustc,
  src,
  unzip,
  watchman,
  yasm,
  zip,
}:

let
  version = "1.21.15b";
  firefoxVersion = "154.0";
  firefoxSource = fetchzip {
    url = "https://archive.mozilla.org/pub/firefox/releases/${firefoxVersion}/source/firefox-${firefoxVersion}.source.tar.xz";
    hash = "sha256-Qo6m7gkRkggBRHucvU2BlwnYN00dHrtaDnbyHEctUmQ=";
  };
  ffprefsCargoDeps = rustPlatform.fetchCargoVendor {
    pname = "zen-ffprefs";
    inherit version;
    src = src + "/tools/ffprefs";
    hash = "sha256-DZMwxeulQiIiSATU0MoyqiUMA0USZq6umhkr67hZH1Q=";
  };
  policies = builtins.toJSON {
    policies = {
      DisableAppUpdate = true;
      ExtensionSettings = {
        "*" = {
          installation_mode = "allowed";
        };
        "{446900e4-71c2-419f-a6a7-df9c091e268b}" = {
          installation_mode = "force_installed";
          install_url = "https://addons.mozilla.org/firefox/downloads/latest/bitwarden-password-manager/latest.xpi";
        };
      };
    };
  };
in
(buildNpmPackage.override { nodejs = nodejs_22; }) {
  pname = "zen-browser";
  inherit version src;

  npmDepsHash = "sha256-2GNKVh2KkW+C2h4xxsmYXRgn5tUuTUh5ZBSVvLUAVoI=";
  cargoDeps = ffprefsCargoDeps;

  nativeBuildInputs = [
    cargo
    clang
    cmake
    git
    gnumake
    gnutar
    mercurial
    nasm
    ninja
    pkg-config
    python311
    rust-cbindgen
    rustPlatform.cargoSetupHook
    rustc
    unzip
    watchman
    yasm
    zip
  ];
  buildInputs = [ cairo ];

  makeCacheWritable = true;
  dontNpmBuild = true;

  preBuild = ''
    export HOME="$TMPDIR/home"
    export MACH_BUILD_PYTHON_NATIVE_PACKAGE_SOURCE=none
    export MOZBUILD_STATE_PATH="$TMPDIR/mozbuild"
    export SURFER_COMPAT=aarch64
    export SURFER_PLATFORM=darwin
    export ZEN_CROSS_COMPILING=0
    export ZEN_GA_DISABLE_PGO=true
    export ZEN_RELEASE=1
    export ZEN_RELEASE_BRANCH=release
    mkdir -p "$HOME" "$MOZBUILD_STATE_PATH" engine
    cp -R ${firefoxSource}/. engine/
    chmod -R u+w engine
  '';

  buildPhase = ''
    runHook preBuild

    npm run surfer -- ci --brand release --display-version ${version}
    npm run import -- --verbose
    npm run build
    npm run package -- --verbose

    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall

    app="$(find engine -type d -name 'Zen.app' -print -quit)"
    test -n "$app"
    mkdir -p "$out/Applications"
    cp -R "$app" "$out/Applications/Zen.app"
    mkdir -p "$out/Applications/Zen.app/Contents/Resources/distribution"
    printf '%s\n' ${lib.escapeShellArg policies} \
      > "$out/Applications/Zen.app/Contents/Resources/distribution/policies.json"
    /usr/bin/codesign --force --deep --sign - --timestamp=none "$out/Applications/Zen.app"

    runHook postInstall
  '';

  meta = {
    description = "Zen Browser built from the managed server source checkout";
    homepage = "https://zen-browser.app";
    license = lib.licenses.mpl20;
    platforms = [ "aarch64-darwin" ];
  };
}
