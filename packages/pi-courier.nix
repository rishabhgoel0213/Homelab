{
  buildNpmPackage,
  fetchFromGitHub,
  fetchurl,
  lib,
  nodejs_24,
}:

let
  version = "0.1.22";
  matrixCrypto = fetchurl {
    url = "https://github.com/matrix-org/matrix-rust-sdk-crypto-nodejs/releases/download/v0.4.0/matrix-sdk-crypto.linux-x64-gnu.node";
    hash = "sha256-cHjU3ZhxKPea/RksT2IfZK3s435D8qh1bx0KnwNN5xg=";
  };
in
buildNpmPackage {
  pname = "pi-courier";
  inherit version;

  src = fetchFromGitHub {
    owner = "Hi-Barry";
    repo = "pi-courier";
    rev = "904718fd34424e502c738b7980f16e62eeadf6c0";
    hash = "sha256-vKcA6PIKI0P6KcOSqFH0C2xApJCpdHVjpI9WgGW52H0=";
  };

  nodejs = nodejs_24;
  npmDepsHash = "sha256-H2b3kJet3DnIhlsgdEi9/Fw9BeMlK4J90/x1CBAa0C0=";
  npmDepsFetcherVersion = 2;
  npmRebuildFlags = [ "--ignore-scripts" ];

  # Upstream's lockfile omitted integrity fields for three nested peer
  # packages. Supply the registry-published hashes so fetchNpmDeps can keep
  # dependency resolution offline and verified.
  postPatch = ''
    sed -i '/node_modules\/@earendil-works\/pi-coding-agent\/node_modules\/@earendil-works\/pi-agent-core": {/,/"license":/ {
      /"resolved":/a\      "integrity": "sha512-RorGp9OH5l3ElpuC5a5ZQ2eWcchZGXflXRzVGkV99y3y6tT+LLNyxoYIdVKvTKWEObwhExeQbTH0fI2tE4iX4g==",
    }' package-lock.json
    sed -i '/node_modules\/@earendil-works\/pi-coding-agent\/node_modules\/@earendil-works\/pi-ai": {/,/"license":/ {
      /"resolved":/a\      "integrity": "sha512-m3IZD4g3er0V8TC9+Vpgw/sjTKqcJlkcIBy/JvsgRubuuik3tAVzyugUg4rVrShIkkOT69mEd34NEqKUIsl6JQ==",
    }' package-lock.json
    sed -i '/node_modules\/@earendil-works\/pi-coding-agent\/node_modules\/@earendil-works\/pi-tui": {/,/"license":/ {
      /"resolved":/a\      "integrity": "sha512-IoYrb0rORjELmEpNtoCA/U8je3KopMkRAVJRdSzvXRvgb+Huo1gNh8Q5CSZvNOiYtDxJdj2tYZZHZ4B3+IN3hA==",
    }' package-lock.json
  '';

  # matrix-sdk-crypto's postinstall downloads this native module from GitHub.
  # Keep the build offline and reproducible by providing the pinned artifact.
  preBuild = ''
    install -m 0644 ${matrixCrypto} \
      node_modules/@matrix-org/matrix-sdk-crypto-nodejs/matrix-sdk-crypto.linux-x64-gnu.node
  '';

  meta = {
    description = "Matrix transport for the Pi coding agent";
    homepage = "https://github.com/Hi-Barry/pi-courier";
    license = lib.licenses.mit;
    mainProgram = "pi-courier";
    platforms = [ "x86_64-linux" ];
  };
}
