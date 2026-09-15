{
  buildNpmPackage,
  lib,
  makeWrapper,
  nodejs_24,
}:

(buildNpmPackage.override { nodejs = nodejs_24; }) {
  pname = "firefox-devtools-mcp-moz";
  version = "0.10.2";

  src = lib.cleanSource ./.;
  npmDepsHash = "sha256-yxzF0iKoGU8VtNFKomH66TgPeX8NLUfWiSMFRS8pZC8=";
  dontNpmBuild = true;
  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/lib/firefox-devtools-mcp/node_modules" "$out/bin"
    cp -R node_modules/. "$out/lib/firefox-devtools-mcp/node_modules/"
    makeWrapper ${nodejs_24}/bin/node "$out/bin/firefox-devtools-mcp" \
      --add-flags "$out/lib/firefox-devtools-mcp/node_modules/@mozilla/firefox-devtools-mcp-moz/dist.moz/index.js"

    runHook postInstall
  '';

  meta = {
    description = "Mozilla Firefox DevTools MCP with privileged browser-chrome tools";
    homepage = "https://github.com/mozilla/firefox-devtools-mcp";
    license = with lib.licenses; [
      mit
      asl20
    ];
    mainProgram = "firefox-devtools-mcp";
    platforms = lib.platforms.unix;
  };
}
