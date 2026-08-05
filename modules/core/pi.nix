{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  piAgentDir = cfg.paths.piAgentDir;
  piPackage = pkgs.callPackage ../../packages/pi-coding-agent.nix { };
  piBin = "${piPackage}/bin/pi";
  piWrapper = pkgs.writeShellScriptBin "pi" ''
    export PI_CODING_AGENT_DIR=${lib.escapeShellArg piAgentDir}
    export HOME=${lib.escapeShellArg cfg.paths.userHome}
    exec ${piBin} "$@"
  '';
  preparePiHome = pkgs.writeShellScript "prepare-pi-home" ''
    set -euo pipefail

    install -d -m 0700 -o rishabh -g users \
      ${lib.escapeShellArg "${cfg.paths.stateRoot}/pi"} \
      ${lib.escapeShellArg piAgentDir} \
      ${lib.escapeShellArg "${piAgentDir}/sessions"} \
      ${lib.escapeShellArg "${piAgentDir}/extensions"} \
      ${lib.escapeShellArg "${piAgentDir}/skills"} \
      ${lib.escapeShellArg "${piAgentDir}/prompts"}

    install -m 0600 -o rishabh -g users \
      ${../../pi/settings.json} \
      ${lib.escapeShellArg "${piAgentDir}/settings.json"}
    install -m 0600 -o rishabh -g users \
      ${../../pi/AGENTS.md} \
      ${lib.escapeShellArg "${piAgentDir}/AGENTS.md"}
    install -m 0600 -o rishabh -g users \
      ${../../pi/extensions/agent-history.ts} \
      ${lib.escapeShellArg "${piAgentDir}/extensions/agent-history.ts"}
  '';
in
{
  environment.systemPackages = [ piWrapper ];

  environment.sessionVariables = {
    PI_CODING_AGENT_DIR = piAgentDir;
  };

  systemd.services.pi-state = {
    description = "Prepare the managed Pi coding-agent state";
    wantedBy = [ "multi-user.target" ];
    restartIfChanged = true;
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = preparePiHome;
    };
  };
}
