{ config, pkgs, ... }:
let
  inherit (config.homelab) paths;
  package = pkgs.callPackage ./package.nix { };
  acp = pkgs.callPackage ./acp-package.nix { };
  # agy always uses $HOME/.gemini; keep that home in managed state like Claude's.
  stateDir = "${paths.stateRoot}/antigravity";
  geminiHome = "${paths.userHome}/.gemini";
  mcp = pkgs.runCommand "antigravity-mcp.json" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    python3 ${./mcp.py} ${../codex/config/server.toml} ${../codex/plugins/umd-canvas/.mcp.json} > "$out"
  '';
  runuser = "${pkgs.util-linux}/bin/runuser -u rishabh --";
in
{
  environment.systemPackages = [
    package
    acp
  ];
  # The ACP runtime's .par cannot be patched; nix-ld runs it unmodified.
  programs.nix-ld.enable = true;
  system.activationScripts.antigravityConfig = {
    deps = [ "users" ];
    text = ''
      install -d -m 0700 -o rishabh -g users ${stateDir} ${stateDir}/config
      if [ ! -e ${geminiHome} ] && [ ! -L ${geminiHome} ]; then
        ln -s ${stateDir} ${geminiHome}
        chown -h rishabh:users ${geminiHome}
      fi
      if [ "$(readlink ${geminiHome})" != ${stateDir} ]; then
        echo "warning: ${geminiHome} is not a link to ${stateDir}; agy will not use managed state" >&2
      fi
      install -m 0600 -o rishabh -g users ${../codex/AGENTS.md} ${stateDir}/config/AGENTS.md
      ${runuser} ${pkgs.python3}/bin/python3 ${../claude/install-mcp.py} ${stateDir}/config/mcp_config.json ${mcp}
    '';
  };
  system.activationScripts.antigravityT3 = {
    deps = [
      "users"
      "antigravityConfig"
    ];
    text = ''
      if [ -d ${paths.t3codeState}/userdata ]; then
        ${runuser} ${pkgs.python3}/bin/python3 ${./t3-settings.py} ${paths.t3codeState}/userdata/settings.json ${acp}/bin/agy-acp-server
      fi
    '';
  };
  systemd.services.antigravity-auto-update = {
    description = "Update managed Antigravity CLI and publish its Mac release";
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
      HOMELAB_DEV_ROOT = paths.devRoot;
      HOMELAB_DEPLOY_ROOT = paths.opsRoot;
      HOST = config.networking.hostName;
    };
    serviceConfig = {
      Type = "oneshot";
      WorkingDirectory = paths.devRoot;
      ExecStart = "${paths.opsRoot}/components/antigravity/bin/auto-update";
    };
  };
  # After t3code-auto-update (06:00) so the ACP runtime follows a same-day T3 bump.
  systemd.timers.antigravity-auto-update = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 06:30:00";
      Persistent = true;
    };
  };
}
