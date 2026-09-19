{ lib, pkgs, ... }:

let
  projectsRoot = "/Users/rishabhgoel/Projects";
  projectctl = pkgs.writeShellApplication {
    name = "projectctl";
    runtimeInputs = [
      pkgs.nix
      pkgs.python3
      pkgs.syncthing
    ];
    text = ''
      export PROJECTS_ROOT=${lib.escapeShellArg projectsRoot}
      export PROJECTCTL_NIX_BIN=${lib.escapeShellArg "${pkgs.nix}/bin/nix"}
      export PROJECTCTL_SELF=/run/current-system/sw/bin/projectctl
      export PROJECTCTL_IDE_BIN=/run/current-system/sw/bin/vscodium-env
      export PROJECTCTL_SYNC_ROLE=target
      export PROJECTCTL_SYNC_PEERS_JSON='{}'
      export PROJECTCTL_SYNCTHING_COMMAND_JSON=${
        lib.escapeShellArg (
          builtins.toJSON [
            "${pkgs.syncthing}/bin/syncthing"
            "cli"
          ]
        )
      }
      exec python3 ${./bin/projectctl.py} "$@"
    '';
  };
in
{
  environment.systemPackages = [ projectctl ];
}
