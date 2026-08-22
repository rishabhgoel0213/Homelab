{ config, lib, pkgs, ... }:

let
  cfg = config.homelab;
  host = "vault.${cfg.internalDomain}";
  stateDir = "${cfg.paths.stateRoot}/vaultwarden";
in
{
  config = lib.mkIf cfg.vaultwarden.enable {
    services.vaultwarden = {
      enable = true;
      domain = host;
      environmentFile = [ config.sops.secrets."vaultwarden.env".path ];
      config = {
        DATA_FOLDER = stateDir;
        ROCKET_ADDRESS = "127.0.0.1";
        ROCKET_PORT = 8222;
        SIGNUPS_ALLOWED = false;
        INVITATIONS_ALLOWED = true;
        WEBSOCKET_ENABLED = true;
      };
    };

    homelab.routes.vault = {
      enable = true;
      host = "vault";
      visibility = "internal";
      upstream = "http://127.0.0.1:8222";
      description = "Vaultwarden password vault";
    };

    systemd.tmpfiles.rules = [
      "d ${stateDir} 0700 vaultwarden vaultwarden - -"
    ];

    systemd.services.vaultwarden.serviceConfig.ReadWritePaths = [ stateDir ];

    assertions = [
      {
        assertion = cfg.secrets.enable;
        message = "homelab.vaultwarden.enable requires homelab.secrets.enable for the admin token environment file.";
      }
      {
        assertion = cfg.acme.enable;
        message = "homelab.vaultwarden.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
