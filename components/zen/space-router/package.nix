{
  lib,
  stdenvNoCC,
  zip,
}:

stdenvNoCC.mkDerivation {
  pname = "zen-space-router-extension";
  version = "1.0.1";

  src = ./extension;
  nativeBuildInputs = [ zip ];

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/share/zen-space-router"
    (
      cd "$src"
      zip -X -q -r "$out/share/zen-space-router/zen-space-router.xpi" .
    )
    runHook postInstall
  '';

  meta = {
    description = "Privileged Zen Browser extension for Jev-backed automatic Space routing";
    platforms = lib.platforms.all;
  };
}
