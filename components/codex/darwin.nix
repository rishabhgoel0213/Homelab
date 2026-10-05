{
  config,
  lib,
  macbookArtifacts,
  pkgs,
  ...
}:

let
  user = "rishabhgoel";
  userHome = "/Users/${user}";
  codexHome = "${userHome}/.codex";
  codexConfig = pkgs.writeText "codex-cli-config.toml" (builtins.readFile ./config/macbook.toml);
  codexPackage = macbookArtifacts.codex;
  stateDir = "${userHome}/Library/Application Support/Homelab/codex";
  clientConfig = pkgs.writeText "codex-mac-client.json" (
    builtins.toJSON {
      inherit stateDir;
      bootstrap = toString codexPackage;
      ssh = "${pkgs.openssh}/bin/ssh";
      sshHost = "rishabh@nixos-pc";
      remoteSocket = "/srv/state/codex/app-server-control/app-server-control.sock";
      releaseFile = "/srv/state/codex-mac-release/current.json";
      nix = "${config.nix.package}/bin/nix";
      nixEnv = "${config.nix.package}/bin/nix-env";
      publicKey = lib.removeSuffix "\n" (builtins.readFile ../darwin-deploy/cache-public-key.txt);
    }
  );
  command =
    name: action:
    pkgs.writeShellScriptBin name ''
      exec ${pkgs.python3}/bin/python3 ${./mac-client.py} --config ${clientConfig} ${action} "$@"
    '';
  codexLauncher = command "codex" "run";
  serverLauncher = command "codex-server" "server";
  updater = command "codex-update" "update";
in
{
  environment.systemPackages = [
    codexLauncher
    serverLauncher
    updater
  ];

  launchd.user.agents.codex-update.serviceConfig = {
    Label = "com.therealrishabh.codex-update";
    ProgramArguments = [ "${updater}/bin/codex-update" ];
    RunAtLoad = true;
    StartInterval = 1800;
    ProcessType = "Background";
    StandardOutPath = "${stateDir}/update.log";
    StandardErrorPath = "${stateDir}/update.err";
    EnvironmentVariables.PATH = "${
      lib.makeBinPath [
        pkgs.openssh
        config.nix.package
      ]
    }:/usr/bin:/bin";
  };

  # Codex.app remains outside Nix, but the app and managed CLI intentionally
  # share ~/.codex configuration and authentication state.
  system.activationScripts.preActivation.text = lib.mkAfter ''
    /usr/bin/codesign --verify --deep --strict ${codexPackage}/CodexCLI.app
    install -d -m 0700 -o ${user} -g staff ${lib.escapeShellArg stateDir}
  '';
  system.activationScripts.postActivation.text = lib.mkAfter ''
    codex_home=${lib.escapeShellArg codexHome}
    config_path="$codex_home/config.toml"

    install -d -m 0700 -o ${user} -g staff "$codex_home"
    install -d -m 0700 -o ${user} -g staff ${lib.escapeShellArg stateDir}
    if [[ -e "$config_path" && ! -L "$config_path" ]]; then
      echo "Refusing to replace unmanaged Codex CLI config at $config_path" >&2
      exit 1
    fi
    ln -sfn ${codexConfig} "$config_path"
    chown -h ${user}:staff "$config_path"
  '';
}
