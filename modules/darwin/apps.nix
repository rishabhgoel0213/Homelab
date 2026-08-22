{
  inputs,
  lib,
  pkgs,
  ...
}:

let
  user = "rishabhgoel";
  userHome = "/Users/${user}";
  codexHome = "${userHome}/.codex";
  codexConfig = pkgs.writeText "codex-cli-config.toml" (
    builtins.readFile ../../config/codex-cli.toml
  );
  codexPackage = pkgs.callPackage ../../packages/codex.nix { };
  codexCli = pkgs.writeShellScriptBin "codex" ''
    export CODEX_HOME=${lib.escapeShellArg codexHome}
    exec ${codexPackage}/bin/codex "$@"
  '';
  tabbyPlugins = pkgs.callPackage ../../packages/tabby-plugins.nix { };
  tabbyTerminal = pkgs.callPackage ../../packages/tabby-terminal.nix {
    src = inputs.tabby-terminal;
    inherit tabbyPlugins;
  };
  zenBrowser = pkgs.callPackage ../../packages/zen-browser.nix {
    src = inputs.zen-browser;
  };
in
{
  environment.systemPackages = [
    codexCli
    tabbyTerminal
    zenBrowser
  ];

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
