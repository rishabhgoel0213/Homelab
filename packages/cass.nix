{
  autoPatchelfHook,
  fetchurl,
  lib,
  stdenv,
  zlib,
}:

let
  version = "0.6.23";
in
stdenv.mkDerivation {
  pname = "coding-agent-session-search";
  inherit version;

  src = fetchurl {
    url = "https://github.com/Dicklesworthstone/coding_agent_session_search/releases/download/v${version}/cass-linux-amd64.tar.gz";
    hash = "sha256-UioJBR5TdvsbpkPFs6jDh9z3moNP0j52n2nMeH7eNkY=";
  };

  sourceRoot = ".";
  nativeBuildInputs = [ autoPatchelfHook ];
  buildInputs = [
    stdenv.cc.cc.lib
    zlib
  ];
  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 cass "$out/bin/cass"
    runHook postInstall
  '';

  doInstallCheck = true;
  installCheckPhase = ''
    test "$($out/bin/cass --version)" = "cass ${version}"
  '';

  meta = {
    description = "Local search and export across coding-agent session stores";
    homepage = "https://github.com/Dicklesworthstone/coding_agent_session_search";
    downloadPage = "https://github.com/Dicklesworthstone/coding_agent_session_search/releases/tag/v${version}";
    license = lib.licenses.mit;
    mainProgram = "cass";
    platforms = [ "x86_64-linux" ];
  };
}
