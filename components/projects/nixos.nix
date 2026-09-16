{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  syncPeers = {
    macbook = {
      device_id = "IQFWOVW-GBBLJ5N-V6DEH6P-CQBKOEQ-62NNNCU-ABWJ5LE-AEHM737-Z722TA4";
      projects_root = "/Users/rishabhgoel/Projects";
      ssh_host = "rishabhgoel@macbook.tail2f4d27.ts.net";
      remote_projectctl = "/run/current-system/sw/bin/projectctl";
    };
  };
  projectctl = pkgs.writeShellApplication {
    name = "projectctl";
    runtimeInputs = [
      pkgs.nix
      pkgs.openssh
      pkgs.python3
      pkgs.syncthing
    ];
    text = ''
      export PROJECTS_ROOT=${lib.escapeShellArg homelab.paths.projectsRoot}
      export PROJECTCTL_JUPYTER_URL=${lib.escapeShellArg "https://lab.${homelab.internalSubdomain}.${homelab.domain}"}
      export PROJECTCTL_JUPYTER_ROOT=/
      export PROJECTCTL_JUPYTER_KERNEL_DIR=${lib.escapeShellArg "${homelab.paths.stateRoot}/jupyterlab/data/kernels"}
      export PROJECTCTL_NIX_BIN=${lib.escapeShellArg "${pkgs.nix}/bin/nix"}
      export PROJECTCTL_SELF=/run/current-system/sw/bin/projectctl
      export PROJECTCTL_SYNC_ROLE=server
      export PROJECTCTL_SYNC_PEERS_JSON=${lib.escapeShellArg (builtins.toJSON syncPeers)}
      export PROJECTCTL_SYNCTHING_COMMAND_JSON=${
        lib.escapeShellArg (
          builtins.toJSON [
            "${pkgs.syncthing}/bin/syncthing"
            "cli"
            "--home=${homelab.paths.stateRoot}/syncthing"
          ]
        )
      }
      export PROJECTCTL_SSH_BIN=${lib.escapeShellArg "${pkgs.openssh}/bin/ssh"}
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
      exec python3 ${./bin/projectctl.py} "$@"
    '';
  };
  projectAlias = pkgs.writeShellScriptBin "project" ''
    exec ${projectctl}/bin/projectctl "$@"
  '';
in
{
  imports = [ ./catalog.nix ];
  environment.systemPackages = [
    projectctl
    projectAlias
  ];
}
