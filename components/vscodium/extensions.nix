{
  pkgs,
  projectsExtension,
  jupyterTempDir ? "/tmp",
}:

let
  openRemoteSsh = pkgs.callPackage ./open-remote-ssh/package.nix { };
  jupyter = pkgs.vscode-extensions.ms-toolsai.jupyter.overrideAttrs (oldAttrs: {
    postPatch = (oldAttrs.postPatch or "") + ''
      rm -f temp
      ln -s ${pkgs.lib.escapeShellArg jupyterTempDir} temp
    '';
  });
  core = [
    projectsExtension
    pkgs.vscode-extensions.editorconfig.editorconfig
    pkgs.vscode-extensions.jnoortheen.nix-ide
    pkgs.vscode-extensions.mkhl.direnv
    pkgs.vscode-extensions.redhat.vscode-yaml
    pkgs.vscode-extensions.tamasfe.even-better-toml
  ];
  c = [ pkgs.vscode-extensions.llvm-vs-code-extensions.vscode-clangd ];
  notebooks = [
    jupyter
    pkgs.vscode-extensions.ms-toolsai.jupyter-renderers
  ];
  python = [
    pkgs.vscode-extensions.ms-python.black-formatter
    pkgs.vscode-extensions.ms-python.debugpy
    pkgs.vscode-extensions.ms-python.python
    pkgs.vscode-extensions.ms-python.vscode-python-envs
  ];
  rust = [ pkgs.vscode-extensions.rust-lang.rust-analyzer ];
  web = [
    pkgs.vscode-extensions.dbaeumer.vscode-eslint
    pkgs.vscode-extensions.esbenp.prettier-vscode
  ];
in
{
  inherit
    c
    core
    notebooks
    python
    rust
    web
    ;

  inherit jupyter;

  full = core ++ c ++ notebooks ++ python ++ rust ++ web;

  remoteClient = [ openRemoteSsh ];
}
