{
  lib,
  pkgs,
  self,
  ...
}:

let
  user = "rishabhgoel";
  userHome = "/Users/${user}";
  codexHome = "${userHome}/.codex";
  codexConfig = pkgs.writeText "codex-cli-config.toml" (builtins.readFile ./config/macbook.toml);
  codexPackage = self.packages.x86_64-linux.macbook-codex;
in
{
  environment.systemPackages = [ codexPackage ];

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
