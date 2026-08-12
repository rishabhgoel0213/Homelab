{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab;
in
{
  config = lib.mkIf cfg.secrets.enable {
    sops = {
      defaultSopsFile = cfg.paths.secretsFile;
      validateSopsFiles = false;
      age.sshKeyPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];

      secrets = {
        "network-manager.env" = { };
        "cloudflare-admin.env" = {
          owner = "rishabh";
          group = "users";
          mode = "0400";
        };
        "cloudflare-dns.env" = { };
        "cloudflared-tunnel.json" = { };
        "tailscale-oauth.env" = {
          owner = "rishabh";
          group = "users";
          mode = "0400";
        };
        "codex-auth.json" = {
          owner = "rishabh";
          group = "users";
          mode = "0400";
        };
        "codex-credentials.json" = {
          owner = "rishabh";
          group = "users";
          mode = "0400";
        };
        "codex-beeper.env" = {
          owner = "rishabh";
          group = "users";
          mode = "0400";
        };
        "vaultwarden.env" = { };
        "samba-password" = {
          owner = "root";
          group = "root";
          mode = "0400";
        };
        "restic-password" = { };
      }
      // lib.optionalAttrs cfg.remotePhone.enable {
        "remote-phone-token" = {
          owner = "rishabh";
          group = "users";
          mode = "0400";
        };
      }
      // lib.optionalAttrs cfg.matrix.enable {
        "matrix-registration-shared-secret" = { };
        "matrix-whatsapp-as-token" = { };
        "matrix-whatsapp-hs-token" = { };
        "matrix-whatsapp-pickle-key" = { };
        "matrix-instagram-as-token" = { };
        "matrix-instagram-hs-token" = { };
        "matrix-instagram-pickle-key" = { };
        "matrix-instagram-provisioning-secret" = { };
        "matrix-imessage-as-token" = { };
        "matrix-imessage-hs-token" = { };
        "matrix-double-puppet-as-token" = { };
        "matrix-double-puppet-hs-token" = { };
        "matrix-double-puppet-sender-localpart" = { };
      }
      // lib.optionalAttrs cfg.pi.courier.enable {
        "matrix-pi-courier-access-token" = {
          owner = "rishabh";
          group = "users";
          mode = "0400";
        };
        "matrix-pi-courier-password" = {
          owner = "root";
          group = "root";
          mode = "0400";
        };
      }
      // lib.optionalAttrs cfg.singlemail.enable {
        "singlemail.env" = {
          owner = "rishabh";
          group = "users";
          mode = "0400";
        };
      }
      // lib.optionalAttrs (cfg.backrest.sshTarget != null) {
        "restic-ssh-key" = {
          owner = "root";
          group = "root";
          mode = "0400";
        };
        "restic-known-hosts" = {
          owner = "root";
          group = "root";
          mode = "0444";
        };
      };
    };
  };
}
