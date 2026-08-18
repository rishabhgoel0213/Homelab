{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  projectctl = pkgs.writeShellApplication {
    name = "projectctl";
    runtimeInputs = [
      pkgs.nix
      pkgs.python3
    ];
    text = ''
      export PROJECTS_ROOT=${lib.escapeShellArg homelab.paths.projectsRoot}
      export PROJECTCTL_JUPYTER_URL=${lib.escapeShellArg "https://lab.${homelab.internalSubdomain}.${homelab.domain}"}
      export PROJECTCTL_JUPYTER_ROOT=/
      export PROJECTCTL_JUPYTER_KERNEL_DIR=${lib.escapeShellArg "${homelab.paths.stateRoot}/jupyterlab/data/kernels"}
      export PROJECTCTL_NIX_BIN=${lib.escapeShellArg "${pkgs.nix}/bin/nix"}
      export PROJECTCTL_SELF=/run/current-system/sw/bin/projectctl
      export PROJECTCTL_HARNESSES_JSON=${
        lib.escapeShellArg (
          builtins.toJSON {
            codex = [
              "/run/current-system/sw/bin/codex"
              "-C"
              "{project}"
            ];
            pi = [ "/run/current-system/sw/bin/pi" ];
          }
        )
      }
      exec python3 ${../../scripts/projectctl.py} "$@"
    '';
  };
  projectAlias = pkgs.writeShellScriptBin "project" ''
    exec ${projectctl}/bin/projectctl "$@"
  '';
in
{
  environment.systemPackages = [
    projectctl
    projectAlias
  ];
}
