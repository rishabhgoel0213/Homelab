{ config, pkgs, ... }:
let
  package = pkgs.callPackage ./package.nix { };
  launcher = pkgs.writeShellScriptBin "claude" ''
    export CLAUDE_CONFIG_DIR=/srv/state/claude
    export DISABLE_AUTOUPDATER=1
    exec ${package}/bin/claude "$@"
  '';
in
{
  environment.systemPackages = [ launcher ];
  system.activationScripts.claudeConfig = {
    deps = [ "users" ];
    text = ''
      install -d -m 0700 -o rishabh -g users /srv/state/claude
      install -m 0600 -o rishabh -g users ${../codex/AGENTS.md} /srv/state/claude/CLAUDE.md
      ${pkgs.util-linux}/bin/runuser -u rishabh -- ${pkgs.python3}/bin/python3 ${./prune-mcp.py} /srv/state/claude/.claude.json codex-scheduler tasks zen-live umd-canvas
    '';
  };
  system.activationScripts.claudeT3 = {
    deps = [
      "users"
      "claudeConfig"
    ];
    text = ''
      if [ -d /srv/state/t3code/userdata ]; then
        ${pkgs.util-linux}/bin/runuser -u rishabh -- ${pkgs.python3}/bin/python3 ${./t3-settings.py} /srv/state/t3code/userdata/settings.json
      fi
    '';
  };
  systemd.services.claude-auto-update = {
    description = "Update managed Claude Code and publish its Mac release";
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    path = with pkgs; [
      bash
      coreutils
      curl
      gawk
      git
      gnugrep
      gnused
      jq
      just
      nix
      nixos-rebuild
      perl
      python3
      sudo
      systemd
      util-linux
    ];
    environment = {
      HOMELAB_DEV_ROOT = config.homelab.paths.devRoot;
      HOMELAB_DEPLOY_ROOT = config.homelab.paths.opsRoot;
      HOST = config.networking.hostName;
    };
    serviceConfig = {
      Type = "oneshot";
      WorkingDirectory = config.homelab.paths.devRoot;
      ExecStart = "${config.homelab.paths.opsRoot}/components/claude/bin/auto-update";
    };
  };
  systemd.timers.claude-auto-update = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 05:00:00";
      Persistent = true;
    };
  };
}
