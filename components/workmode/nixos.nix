{ config, pkgs, ... }:
let python = pkgs.python3.withPackages (p: [ p.websocket-client ]);
in {
  systemd.services.workmode-brick = {
    description = "Authenticated phone Brick state relay";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" "tailscaled.service" "sops-nix.service" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      ExecStart = "${python}/bin/python ${./brick_bridge.py} --token-file %d/phone-token --state-file /var/lib/workmode-brick/latch.json";
      LoadCredential = "phone-token:${config.sops.secrets.remote-phone-token.path}";
      DynamicUser = true;
      StateDirectory = "workmode-brick";
      UMask = "0077";
      Restart = "always";
      RestartSec = 3;
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
      RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
    };
  };
  networking.firewall.interfaces.tailscale0.allowedTCPPorts = [ 8127 ];
}
