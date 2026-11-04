{ pkgs, ... }:

let
  withNix = pkgs.writeShellApplication {
    name = "with-nix";
    runtimeInputs = [ pkgs.nix ];
    text = ''
      export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-/tmp/codex-nix-cache}"
      export NIX_CONFIG="''${NIX_CONFIG:-experimental-features = nix-command flakes}"
      exec nix "$@"
    '';
  };
in
{
  environment.systemPackages = [
    withNix
  ];

  environment.etc = {
    "agents/AGENTS.md".source = ../../AGENTS.md;
  };
}
