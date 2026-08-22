{ config, lib, pkgs, ... }:

let
  cfg = config.homelab;
in
{
  config = lib.mkIf cfg.samba.enable {
    services.samba = {
      enable = true;
      openFirewall = false;
      nmbd.enable = false;
      winbindd.enable = false;

      settings = {
        global = {
          "workgroup" = "WORKGROUP";
          "server string" = "nixos-pc private file share";
          "netbios name" = "NIXOS-PC";
          "server role" = "standalone server";
          "security" = "user";
          "map to guest" = "Never";
          "invalid users" = [
            "root"
          ];

          # Tailscale uses a /32 interface address, which Samba does not bind
          # to reliably. Keep the port closed on non-tailnet interfaces with
          # the host firewall and Samba's hosts allow/deny checks.
          "bind interfaces only" = "no";
          "hosts allow" = "127.0.0.1 100.64.0.0/10";
          "hosts deny" = "0.0.0.0/0";

          "disable netbios" = "yes";
          "smb ports" = "445";
          "server min protocol" = "SMB2";

          "load printers" = "no";
          "printing" = "bsd";
          "printcap name" = "/dev/null";
          "disable spoolss" = "yes";
        };

        Remote = {
          "path" = cfg.paths.remoteShare;
          "comment" = "Rishabh remote server files";
          "valid users" = "rishabh";
          "force user" = "rishabh";
          "force group" = "users";
          "read only" = "no";
          "browseable" = "yes";
          "guest ok" = "no";
          "create mask" = "0644";
          "directory mask" = "0755";

          "ea support" = "yes";
          "vfs objects" = "catia fruit streams_xattr";
          "fruit:metadata" = "stream";
          "fruit:model" = "MacSamba";
          "fruit:veto_appledouble" = "no";
        };
      };
    };

    systemd.services.samba-passdb-rishabh = {
      description = "Synchronize Samba password for rishabh";
      before = [ "samba-smbd.service" ];
      wantedBy = [ "samba.target" ];
      path = with pkgs; [
        coreutils
        samba
      ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        test -s ${config.sops.secrets."samba-password".path}

        password="$(cat ${config.sops.secrets."samba-password".path})"
        if pdbedit -L -u rishabh >/dev/null 2>&1; then
          printf '%s\n%s\n' "$password" "$password" | smbpasswd -s rishabh
        else
          printf '%s\n%s\n' "$password" "$password" | smbpasswd -s -a rishabh
        fi
        smbpasswd -e rishabh
      '';
    };

    systemd.services.samba-smbd = {
      requires = [ "samba-passdb-rishabh.service" ];
      after = [
        "samba-passdb-rishabh.service"
        "tailscaled.service"
      ];
      wants = [ "tailscaled.service" ];
    };

    assertions = [
      {
        assertion = cfg.secrets.enable;
        message = "homelab.samba.enable requires homelab.secrets.enable for the SMB password.";
      }
      {
        assertion = cfg.tailnetIp != null;
        message = "homelab.samba.enable requires homelab.tailnetIp so the share can stay tailnet-scoped.";
      }
    ];
  };
}
