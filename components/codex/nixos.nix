{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  codexHome = cfg.paths.codexHome;
  codexPackage = pkgs.callPackage ./package.nix { };
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
  environment.systemPackages = [
    codexWrapper
  ];

  # Refresh managed client configuration on activation without restarting
  # interactive Codex sessions.
  system.activationScripts.codexConfig = {
    deps = [ "users" ];
    text = ''
      install -d -m 0700 -o rishabh -g users ${lib.escapeShellArg codexHome}
      install -d -m 0700 -o rishabh -g users \
        ${lib.escapeShellArg "${codexHome}/cache"} \
        ${lib.escapeShellArg "${codexHome}/log"} \
        ${lib.escapeShellArg "${codexHome}/plugins"} \
        ${lib.escapeShellArg "${codexHome}/tmp"}
      install -m 0600 -o rishabh -g users \
        ${pkgs.writeText "codex-server-config.toml" (builtins.readFile ./config/server.toml)} \
        ${lib.escapeShellArg "${codexHome}/config.toml"}
      install -m 0600 -o rishabh -g users \
        ${pkgs.writeText "codex-server-agents.md" (builtins.readFile ./AGENTS.md)} \
        ${lib.escapeShellArg "${codexHome}/AGENTS.md"}
    '';
  };

  environment.sessionVariables = {
    CODEX_HOME = codexHome;
  };

  systemd.services.codex-home = {
    description = "Seed managed Codex runtime home";
    wantedBy = [ "multi-user.target" ];
    after = lib.optional cfg.secrets.enable "sops-nix.service";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${prepareCodexHome}";
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
      gh
      jq
      just
      nix
      nixos-rebuild
      perl
      sudo
      systemd
      util-linux
    ];
    environment = {
      HOMELAB_DEV_ROOT = cfg.paths.devRoot;
      HOMELAB_DEPLOY_ROOT = cfg.paths.opsRoot;
      HOST = config.networking.hostName;
    };
    serviceConfig = {
      Type = "oneshot";
      WorkingDirectory = cfg.paths.devRoot;
      ExecStart = "${cfg.paths.opsRoot}/components/codex/bin/auto-update";
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
