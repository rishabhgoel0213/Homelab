{
  fetchurl,
  lib,
  vscode-utils,
}:

vscode-utils.buildVscodeExtension {
  pname = "jeanp413-open-remote-ssh";
  version = "0.3.1";

  src = fetchurl {
    url = "https://open-vsx.org/api/jeanp413/open-remote-ssh/0.3.1/file/jeanp413.open-remote-ssh-0.3.1.vsix";
    hash = "sha256-xvFrIlq4aSXyvZ6Mxbox5hSXjM+hIPFQm99umeW+8T8=";
  };

  vscodeExtPublisher = "jeanp413";
  vscodeExtName = "open-remote-ssh";
  vscodeExtUniqueId = "jeanp413.open-remote-ssh";

  meta = {
    description = "Open Remote SSH extension for VSCodium and Code OSS";
    homepage = "https://github.com/jeanp413/open-remote-ssh";
    license = lib.licenses.mit;
  };
}
