{
  buildNpmPackage,
  lib,
}:

buildNpmPackage {
  pname = "tabby-managed-plugins";
  version = "2026-08-22";

  src = ../tabby-plugins;
  npmDepsHash = "sha256-/cqS9qJEocp78oxqJ+b9yc2XQuGkYY0l7JTtzq5anJg=";
  npmFlags = [ "--legacy-peer-deps" ];
  dontNpmBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p "$out/lib/tabby/plugins"
    cp -R node_modules/. "$out/lib/tabby/plugins/"

    runHook postInstall
  '';

  meta = {
    description = "Declaratively managed third-party plugins for Tabby Terminal";
    license = lib.licenses.mit;
    platforms = lib.platforms.darwin;
  };
}
