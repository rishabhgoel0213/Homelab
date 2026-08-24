{
  buildNpmPackage,
  cargo,
  fetchzip,
  git,
  lib,
  nodejs_22,
  pkg-config,
  python311,
  rustPlatform,
  rustc,
  src,
  vips,
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
in
(buildNpmPackage.override { nodejs = nodejs_22; }) {
  pname = "zen-browser-engine-source";
  inherit version src;

  npmDepsHash = "sha256-2GNKVh2KkW+C2h4xxsmYXRgn5tUuTUh5ZBSVvLUAVoI=";
  npmRebuildFlags = [ "--build-from-source" ];
  cargoDeps = ffprefsCargoDeps;
  cargoRoot = "tools/ffprefs";

  nativeBuildInputs = [
    cargo
    git
    pkg-config
    python311
    rustPlatform.cargoSetupHook
    rustc
  ];
  buildInputs = [ vips ];

  makeCacheWritable = true;
  dontNpmBuild = true;
  dontFixup = true;

  buildPhase = ''
    runHook preBuild

    export HOME="$TMPDIR/home"
    mkdir -p "$HOME" engine
    cp -R ${firefoxSource}/. engine/
    chmod -R u+w engine

    # Mozilla source archives do not contain VCS metadata, while Surfer uses
    # git-apply to import Zen's patch stack. An empty local repository is
    # sufficient and is removed from the prepared source output below.
    git -C engine init --quiet

    npm run surfer -- ci --brand release --display-version ${version}
    npm run import -- --verbose

    printf '%s\n' ${lib.escapeShellArg version} \
      > engine/browser/config/version.txt
    printf '%s\n' ${lib.escapeShellArg version} \
      > engine/browser/config/version_display.txt
    rm -rf engine/.git engine/obj-*-apple-darwin

    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall

    mkdir -p "$out"
    # Surfer imports Zen-owned files as absolute symlinks into this temporary
    # build tree. Materialize them so the prepared source remains valid after
    # the build sandbox is removed.
    cp -RL engine/. "$out/"

    runHook postInstall
  '';

  meta = {
    description = "Firefox source with the managed Zen Browser patch stack imported";
    homepage = "https://zen-browser.app";
    license = lib.licenses.mpl20;
    platforms = lib.platforms.linux;
  };
}
