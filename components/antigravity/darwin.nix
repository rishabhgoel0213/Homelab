{
  config,
  lib,
  macbookArtifacts,
  pkgs,
  ...
}:
let
  stateDir = "/Users/rishabhgoel/Library/Application Support/Homelab/antigravity";
  clientConfig = pkgs.writeText "antigravity-mac-client.json" (
    builtins.toJSON {
      inherit stateDir;
      bootstrap = macbookArtifacts.antigravity;
      ssh = "${pkgs.openssh}/bin/ssh";
      sshHost = "rishabh@nixos-pc";
      releaseFile = "/srv/state/antigravity-mac-release/current.json";
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
  launcher = command "agy" "run";
  updater = command "agy-update" "update";
in
{
  environment.systemPackages = [
    launcher
    updater
  ];
  launchd.user.agents.antigravity-update.serviceConfig = {
    Label = "com.therealrishabh.antigravity-update";
    ProgramArguments = [ "${updater}/bin/agy-update" ];
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
  system.activationScripts.preActivation.text = lib.mkAfter ''
    /usr/bin/codesign --verify --strict ${macbookArtifacts.antigravity}/bin/agy
    install -d -m 0700 -o rishabhgoel -g staff ${lib.escapeShellArg stateDir}
  '';
}
