{ config, lib, pkgs, ... }:

let
  inherit (lib) mkIf;

  cfg = config.homelab;
  hasSftpRepository = cfg.backrest.repository != null && cfg.backrest.sshTarget != null;
  sshTargetParts = lib.splitString "@" (cfg.backrest.sshTarget or "");
  sshTargetIsUserHost = builtins.length sshTargetParts == 2;
  sshUser = if sshTargetIsUserHost then builtins.elemAt sshTargetParts 0 else "";
  sshHost = if sshTargetIsUserHost then builtins.elemAt sshTargetParts 1 else "";
in
{
  config = lib.mkIf cfg.backrest.enable {
    systemd.tmpfiles.rules = [
      "d ${cfg.paths.stateRoot}/backrest 0700 root root - -"
      "d ${cfg.paths.stateRoot}/backrest/ssh 0700 root root - -"
      "d ${cfg.paths.stateRoot}/backrest/tmp 0700 root root - -"
      "d ${cfg.paths.stateRoot}/backrest/cache 0700 root root - -"
    ];

    systemd.services.backrest-ssh-config = mkIf hasSftpRepository {
      description = "Prepare SSH config for Backrest Restic SFTP repositories";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = with pkgs; [
        coreutils
      ];
      script = ''
        install -d -m 0700 -o root -g root ${cfg.paths.stateRoot}/backrest/ssh
        install -m 0600 -o root -g root ${config.sops.secrets."restic-ssh-key".path} ${cfg.paths.stateRoot}/backrest/ssh/restic-ssh-key
        install -m 0644 -o root -g root ${config.sops.secrets."restic-known-hosts".path} ${cfg.paths.stateRoot}/backrest/ssh/known_hosts
        cat > ${cfg.paths.stateRoot}/backrest/ssh/config <<'EOF'
        Host hetzner-storage-box
          HostName ${sshHost}
          User ${sshUser}
          Port ${toString cfg.backrest.sshPort}
          IdentityFile /root/.ssh/restic-ssh-key
          UserKnownHostsFile /root/.ssh/known_hosts
          StrictHostKeyChecking yes
          BatchMode yes
          IdentitiesOnly yes
        EOF
        chmod 0600 ${cfg.paths.stateRoot}/backrest/ssh/config
      '';
    };

    systemd.services.docker-backrest = mkIf hasSftpRepository {
      requires = [ "backrest-ssh-config.service" ];
      after = [ "backrest-ssh-config.service" ];
    };

    virtualisation.oci-containers.containers.backrest = {
      image = cfg.backrest.image;
      autoStart = true;
      # Tailscale's exit-node policy captures RFC1918 Docker bridge subnets,
      # breaking both the local proxy path and Backrest's outbound SFTP. Keep
      # Backrest explicitly loopback-only while avoiding the bridge conflict.
      cmd = [ "/backrest" "-bind-address" "127.0.0.1:9898" ];
      extraOptions = [ "--network=host" ];
      volumes = [
        "${cfg.paths.stateRoot}/backrest:/data"
        "${cfg.paths.stateRoot}/backrest/cache:/cache"
        "${cfg.paths.stateRoot}/backrest/tmp:/tmp"
        "${cfg.paths.stateRoot}/backrest/ssh:/root/.ssh:ro"
        "${cfg.paths.stateRoot}:${cfg.paths.stateRoot}:ro"
        "${cfg.paths.stateRoot}:/backup/srv/state:ro"
        "${cfg.paths.opsRoot}:/backup/srv/ops:ro"
        "/etc/nixos:/backup/etc/nixos:ro"
        "${cfg.paths.userHome}:/backup/home/rishabh:ro"
      ];
      environment = {
        BACKREST_CONFIG = "/data/config.json";
        BACKREST_DATA = "/data";
        XDG_CACHE_HOME = "/cache";
        TMPDIR = "/tmp";
        TZ = config.time.timeZone;
      };
      pull = "missing";
    };

    homelab.routes.backups = {
      enable = true;
      host = "backups";
      visibility = "internal";
      upstream = "http://127.0.0.1:9898";
      description = "Backrest restic UI";
    };

    assertions = [
      {
        assertion = cfg.acme.enable;
        message = "homelab.backrest.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
      {
        assertion = !hasSftpRepository || cfg.secrets.enable;
        message = "Backrest-managed Hetzner backups require homelab.secrets.enable for Restic SSH material.";
      }
      {
        assertion = !hasSftpRepository || sshTargetIsUserHost;
        message = "homelab.backrest.sshTarget must be formatted as user@host for Backrest SSH config generation.";
      }
      {
        assertion = cfg.backrest.repository != null;
        message = "homelab.backrest.repository must be set before enabling Backrest.";
      }
    ];
  };
}
