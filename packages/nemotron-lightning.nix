{ pkgs }:

let
  source = pkgs.lib.cleanSource ../local-models/nemotron-lightning;
  downloader = pkgs.writeShellApplication {
    name = "nemotron-lightning-download";
    runtimeInputs = [
      pkgs.bash
      pkgs.coreutils
      pkgs.jq
      pkgs.python3Packages.huggingface-hub
    ];
    text = ''
      exec bash ${source}/download-model.sh "$@"
    '';
  };
  proxy = pkgs.writeShellApplication {
    name = "nemotron-lightning-proxy";
    runtimeInputs = [ pkgs.nodejs_24 ];
    text = ''
      exec node ${source}/proxy.mjs "$@"
    '';
  };
in
{
  inherit downloader proxy;
}
