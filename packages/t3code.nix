{
  cacert,
  fetchPnpmDeps,
  fetchurl,
  jq,
  lib,
  makeWrapper,
  node-gyp,
  nodejs_24,
  pkg-config,
  pnpmConfigHook,
  pnpm_11,
  python3,
  stdenv,
  sourceCheckout,
  revision,
  mobileUpdatesUrl ? null,
}:

let
  pnpm = pnpm_11.override {
    version = "11.10.0";
    hash = "sha256-YgtmBepPYvxWptCphzP0eQcdAyHgPkhrUix+mnRhdDE=";
  };
  source = builtins.fetchGit {
    url = "file://${sourceCheckout}";
    rev = revision;
  };
in
stdenv.mkDerivation (finalAttrs: {
  pname = "t3code";
  version = "0.0.32-nightly.20260803.985-${builtins.substring 0 9 revision}";

  src = source;

  pnpmDeps = fetchPnpmDeps {
    inherit (finalAttrs) pname version src;
    inherit pnpm;
    fetcherVersion = 4;
    hash = "sha256-We5f789rnOTtp1B13NsIAhT4ww+FduJLtI15073pwJY=";
  };

  nativeBuildInputs = [
    makeWrapper
    node-gyp
    nodejs_24
    pkg-config
    pnpm
    pnpmConfigHook
    python3
  ]
  ++ lib.optional (mobileUpdatesUrl != null) jq;

  # The server and web build do not use Electron. Its workspace dependency is
  # still present in the lockfile, so keep its install hook offline.
  ELECTRON_SKIP_BINARY_DOWNLOAD = "1";
  PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
  PUPPETEER_SKIP_DOWNLOAD = "1";
  SSL_CERT_FILE = "${cacert}/etc/ssl/certs/ca-bundle.crt";

  buildPhase = ''
    runHook preBuild

    # pnpmConfigHook intentionally suppresses lifecycle scripts. Build the one
    # native dependency the server uses for terminals before bundling.
    export npm_config_nodedir=${nodejs_24}
    nodePtyDir="$(find node_modules/.pnpm -path '*/node_modules/node-pty' -type d -print -quit)"
    if [[ -z "$nodePtyDir" ]]; then
      echo "node-pty dependency was not installed" >&2
      exit 1
    fi
    pushd "$nodePtyDir"
    node-gyp rebuild
    node scripts/post-install.js
    popd

    pnpm --filter @t3tools/web build
    pnpm --filter t3 build:bundle

    ${lib.optionalString (mobileUpdatesUrl != null) ''
      export APP_VARIANT=preview
      export EXPO_NO_DOTENV=1
      export T3CODE_MOBILE_UPDATES_URL=${lib.escapeShellArg mobileUpdatesUrl}

      mobileDist="$PWD/mobile-dist"
      # Resolve the fingerprint from the generated native project, matching
      # the locally built bootstrap APK rather than managed-workflow inputs.
      pnpm --filter @t3tools/mobile exec expo prebuild \
        --clean \
        --platform android
      pnpm --filter @t3tools/mobile exec expo export \
        --platform android \
        --output-dir "$mobileDist" \
        --clear
      pnpm --filter @t3tools/mobile exec expo config --type public --json \
        > "$mobileDist/expoConfig.json"
      runtimeVersion="$(${lib.getExe jq} -r .runtimeVersion < <(
        pnpm --filter @t3tools/mobile exec expo-updates \
          runtimeversion:resolve --platform android
      ))"
      test -n "$runtimeVersion"
      test "$runtimeVersion" != null
      printf '%s\n' "$runtimeVersion" > "$mobileDist/runtime-version"
    ''}

    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall

    pnpm --filter t3 \
      --offline \
      --config.inject-workspace-packages=true \
      --config.shamefully-hoist=true \
      deploy --prod "$out/libexec/t3code"

    rm -rf "$out/libexec/t3code/dist/client"
    cp -R apps/web/dist "$out/libexec/t3code/dist/client"

    makeWrapper ${lib.getExe nodejs_24} "$out/bin/t3code" \
      --add-flags "$out/libexec/t3code/dist/bin.mjs"

    ${lib.optionalString (mobileUpdatesUrl != null) ''
      runtimeVersion="$(< mobile-dist/runtime-version)"
      updateDir="$out/share/t3code/mobile-updates/$runtimeVersion/${revision}"
      mkdir -p "$updateDir"
      cp -R mobile-dist/. "$updateDir/"
      rm "$updateDir/runtime-version"
      # Nix normalizes store mtimes to the Unix epoch. Expo uses createdAt to
      # reject updates older than the embedded bundle, so carry the pinned Git
      # commit time as deterministic release metadata instead.
      printf '%s\n' ${toString source.lastModified} > "$updateDir/created-at"
    ''}

    runHook postInstall
  '';

  passthru = {
    inherit pnpm revision sourceCheckout;
  };

  meta = {
    description = "Minimal web GUI for coding agents, pinned to the private Pi-enabled fork";
    homepage = "https://github.com/rishabhgoel0213/t3code";
    license = lib.licenses.mit;
    mainProgram = "t3code";
    platforms = lib.platforms.linux;
  };
})
