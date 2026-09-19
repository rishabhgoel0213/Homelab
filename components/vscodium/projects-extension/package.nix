{ stdenvNoCC }:

stdenvNoCC.mkDerivation {
  pname = "vscode-extension-therealrishabh-projects";
  version = "1.0.0";
  src = ./.;

  installPhase = ''
    runHook preInstall
    destination="$out/share/vscode/extensions/therealrishabh.projects"
    mkdir -p "$destination"
    cp package.json extension.js "$destination/"
    runHook postInstall
  '';

  passthru = {
    vscodeExtName = "projects";
    vscodeExtPublisher = "therealrishabh";
    vscodeExtUniqueId = "therealrishabh.projects";
  };
}
