{
  lib,
  pkgs,
  ...
}:

let
  user = "rishabhgoel";
  userHome = "/Users/${user}";
  codexHome = "${userHome}/.codex";
  codexConfig = pkgs.writeText "codex-cli-config.toml" (
    builtins.readFile ./config/macbook.toml
  );
  codexPackage = pkgs.callPackage ./package.nix { };
  codexCli = pkgs.writeShellScriptBin "codex" ''
    export CODEX_HOME=${lib.escapeShellArg codexHome}
    exec ${codexPackage}/bin/codex "$@"
  '';
in
{
  environment.systemPackages = [ codexCli ];

  # Codex.app remains outside Nix, but the app and managed CLI intentionally
  # share ~/.codex configuration and authentication state.
  system.activationScripts.postActivation.text = lib.mkAfter ''
    codex_home=${lib.escapeShellArg codexHome}
    config_path="$codex_home/config.toml"

    install -d -m 0700 -o ${user} -g staff "$codex_home"
    if [[ -e "$config_path" && ! -L "$config_path" ]]; then
      echo "Refusing to replace unmanaged Codex CLI config at $config_path" >&2
      exit 1
    fi
    ln -sfn ${codexConfig} "$config_path"
    chown -h ${user}:staff "$config_path"
  '';
}
