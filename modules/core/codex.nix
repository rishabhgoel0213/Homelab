{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  codexHome = cfg.paths.codexHome;
  codexPackage = pkgs.callPackage ../../packages/codex.nix { };
  codexBin = "${codexPackage}/bin/codex";
  codexWrapper = pkgs.writeShellScriptBin "codex" ''
    export CODEX_HOME=${lib.escapeShellArg codexHome}
    export HOME=${lib.escapeShellArg cfg.paths.userHome}
    exec ${codexBin} "$@"
  '';
  prepareCodexHome = pkgs.writeShellScript "prepare-codex-home" ''
    set -euo pipefail

    install -d -m 0700 -o rishabh -g users ${lib.escapeShellArg codexHome}
    install -d -m 0700 -o rishabh -g users \
      ${lib.escapeShellArg "${codexHome}/cache"} \
      ${lib.escapeShellArg "${codexHome}/log"} \
      ${lib.escapeShellArg "${codexHome}/plugins"} \
      ${lib.escapeShellArg "${codexHome}/tmp"}

    if [[ -r ${lib.escapeShellArg cfg.paths.codexConfigSource} ]]; then
      install -m 0600 -o rishabh -g users \
        ${lib.escapeShellArg cfg.paths.codexConfigSource} \
        ${lib.escapeShellArg "${codexHome}/config.toml"}
    fi
    if [[ -r ${lib.escapeShellArg cfg.paths.codexAgentsSource} ]]; then
      install -m 0600 -o rishabh -g users \
        ${lib.escapeShellArg cfg.paths.codexAgentsSource} \
        ${lib.escapeShellArg "${codexHome}/AGENTS.md"}
    fi

    ${lib.optionalString cfg.secrets.enable ''
      # Codex rotates refresh tokens in place. Restore the SOPS snapshot only
      # when runtime state is absent so a restart cannot replace the current
      # token with an older, already-used one.
      if [[ ! -s ${lib.escapeShellArg "${codexHome}/auth.json"} ]] \
        && [[ -r ${lib.escapeShellArg config.sops.secrets."codex-auth.json".path} ]]; then
        install -m 0600 -o rishabh -g users \
          ${lib.escapeShellArg config.sops.secrets."codex-auth.json".path} \
          ${lib.escapeShellArg "${codexHome}/auth.json"}
      fi
      if [[ ! -s ${lib.escapeShellArg "${codexHome}/.credentials.json"} ]] \
        && [[ -r ${lib.escapeShellArg config.sops.secrets."codex-credentials.json".path} ]]; then
        install -m 0600 -o rishabh -g users \
          ${lib.escapeShellArg config.sops.secrets."codex-credentials.json".path} \
          ${lib.escapeShellArg "${codexHome}/.credentials.json"}
      fi
    ''}
  '';
in
{
  environment.systemPackages = [ codexWrapper ];

  environment.sessionVariables = {
    CODEX_HOME = codexHome;
  };

  systemd.services.codex-remote-control = {
    description = "Codex remote-control app server";
    restartIfChanged = false;
    wantedBy = [ "multi-user.target" ];
    wants = [
      "network-online.target"
      "tailscaled.service"
    ];
    after = [
      "network-online.target"
      "tailscaled.service"
    ]
    ++ lib.optional cfg.secrets.enable "sops-nix.service";
    path = with pkgs; [
      bash
      bubblewrap
      coreutils
      git
      just
      nix
      openssh
      ripgrep
    ];
    environment = {
      CODEX_HOME = codexHome;
      HOME = cfg.paths.userHome;
      SHELL = "${pkgs.bash}/bin/bash";
    };
    serviceConfig = {
      Type = "simple";
      User = "rishabh";
      Group = "users";
      WorkingDirectory = cfg.paths.agentCockpit;
      ExecStartPre = "${prepareCodexHome}";
      ExecStart = "${codexBin} app-server --remote-control --listen unix://";
      Restart = "always";
      RestartSec = "5s";
    }
    // lib.optionalAttrs cfg.secrets.enable {
      EnvironmentFile = config.sops.secrets."codex-beeper.env".path;
    };
  };

  systemd.services.codex-auto-update = {
    description = "Automatically update the managed Codex package";
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    path = with pkgs; [
      bash
      coreutils
      gawk
      git
      gnugrep
      gnused
      jq
      nix
      nixos-rebuild
      perl
      sudo
      systemd
      util-linux
    ];
    environment = {
      CODEX_OPS_ROOT = cfg.paths.opsRoot;
      HOST = config.networking.hostName;
    };
    serviceConfig = {
      Type = "oneshot";
      WorkingDirectory = cfg.paths.opsRoot;
      ExecStart = "${cfg.paths.opsRoot}/scripts/codex-auto-update";
    };
  };

  systemd.timers.codex-auto-update = {
    description = "Daily managed Codex package update";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 04:30:00";
      Persistent = true;
      Unit = "codex-auto-update.service";
    };
  };
}
