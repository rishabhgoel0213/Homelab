{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
  scheduler = pkgs.callPackage ./package.nix { };
  stateDirectory = "${cfg.paths.stateRoot}/codex-scheduler";
  roots = [
    cfg.paths.projectsRoot
    "${cfg.paths.userHome}/Documents"
    cfg.paths.opsRoot
  ];
in
{
  environment.systemPackages = [ scheduler ];

  systemd.tmpfiles.rules = [
    "d ${stateDirectory} 0700 rishabh users -"
  ];

  systemd.services.codex-scheduler = {
    description = "Dispatch persistent local Codex jobs";
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
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
      CODEX_HOME = cfg.paths.codexHome;
      HOME = cfg.paths.userHome;
      SHELL = "${pkgs.bash}/bin/bash";
      CODEX_SCHEDULER_STATE = stateDirectory;
      CODEX_SCHEDULER_ROOTS = builtins.toJSON roots;
      CODEX_SCHEDULER_CODEX = "/run/current-system/sw/bin/codex";
    };
    serviceConfig = {
      Type = "oneshot";
      User = "rishabh";
      Group = "users";
      WorkingDirectory = stateDirectory;
      ExecStart = "${scheduler}/bin/codex-scheduler tick";
      TimeoutStartSec = "infinity";
      TimeoutStopSec = "15s";
      KillMode = "control-group";
      UMask = "0077";
    };
  };

  systemd.timers.codex-scheduler = {
    description = "Check local Codex schedules every minute";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* *:*:00";
      AccuracySec = "1s";
      Persistent = true;
      Unit = "codex-scheduler.service";
    };
  };

  # Keep the immutable source config managed by the existing Codex module.
  assertions = [
    {
      assertion = lib.hasPrefix "/srv/state/" stateDirectory;
      message = "Codex scheduler state must live under /srv/state.";
    }
  ];
}
