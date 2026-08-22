{ config, lib, pkgs, ... }:

let
  cfg = config.homelab;
  cloudflaredTunnelUnit = "cloudflared-tunnel-${cfg.publicTunnel.tunnelId}.service";
  ip = "${pkgs.iproute2}/bin/ip";

  cfctl = pkgs.writeShellApplication {
    name = "cfctl";
    runtimeInputs = with pkgs; [
      cloudflared
      coreutils
      curl
      flarectl
      jq
      wrangler
    ];
    text = ''
      set -euo pipefail

      env_file="''${CLOUDFLARE_ENV_FILE:-/run/secrets/cloudflare-admin.env}"

      load_env() {
        if [[ -r "$env_file" ]]; then
          set -a
          # shellcheck disable=SC1090
          . "$env_file"
          set +a
        fi
      }

      need_token() {
        load_env
        if [[ -z "''${CLOUDFLARE_API_TOKEN:-}" ]]; then
          echo "Missing CLOUDFLARE_API_TOKEN. Create /home/rishabh/.config/homelab/secrets.yaml and enable homelab.secrets." >&2
          exit 1
        fi
      }

      api() {
        method="$1"
        path="$2"
        body="''${3:-}"

        if [[ -n "$body" ]]; then
          curl --fail-with-body --silent --show-error \
            --request "$method" \
            --header "Authorization: Bearer ''${CLOUDFLARE_API_TOKEN}" \
            --header "Content-Type: application/json" \
            --data "$body" \
            "https://api.cloudflare.com/client/v4$path"
        else
          curl --fail-with-body --silent --show-error \
            --request "$method" \
            --header "Authorization: Bearer ''${CLOUDFLARE_API_TOKEN}" \
            --header "Content-Type: application/json" \
            "https://api.cloudflare.com/client/v4$path"
        fi
      }

      case "''${1:-help}" in
        help|-h|--help)
          cat <<'EOF'
cfctl: Cloudflare control helper

Usage:
  cfctl verify
  cfctl whoami
  cfctl zones
  cfctl dns
  cfctl api METHOD /path [json-body]
  cfctl tunnel-login
  cfctl tunnel-create NAME
  cfctl tunnel-list
  cfctl wrangler ...
  cfctl flarectl ...

Reads credentials from:
  /run/secrets/cloudflare-admin.env

Expected variables:
  CLOUDFLARE_API_TOKEN
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_ZONE_ID
  CLOUDFLARE_ZONE=therealrishabh.com
EOF
          ;;
        verify)
          need_token
          api GET /user/tokens/verify | jq .
          ;;
        whoami)
          need_token
          api GET /user | jq .
          ;;
        zones)
          need_token
          zone="''${CLOUDFLARE_ZONE:-therealrishabh.com}"
          api GET "/zones?name=$zone" | jq .
          ;;
        dns)
          need_token
          if [[ -z "''${CLOUDFLARE_ZONE_ID:-}" ]]; then
            echo "Missing CLOUDFLARE_ZONE_ID in $env_file" >&2
            exit 1
          fi
          api GET "/zones/''${CLOUDFLARE_ZONE_ID}/dns_records" | jq .
          ;;
        api)
          need_token
          if [[ $# -lt 3 || $# -gt 4 ]]; then
            echo "usage: cfctl api METHOD /path [json-body]" >&2
            exit 2
          fi
          shift
          api "$@" | jq .
          ;;
        tunnel-login)
          exec cloudflared tunnel login
          ;;
        tunnel-create)
          shift
          if [[ $# -ne 1 ]]; then
            echo "usage: cfctl tunnel-create NAME" >&2
            exit 2
          fi
          exec cloudflared tunnel create "$1"
          ;;
        tunnel-list)
          exec cloudflared tunnel list
          ;;
        wrangler)
          load_env
          shift
          exec wrangler "$@"
          ;;
        flarectl)
          load_env
          if [[ -n "''${CLOUDFLARE_API_TOKEN:-}" && -z "''${CF_API_TOKEN:-}" ]]; then
            export CF_API_TOKEN="''${CLOUDFLARE_API_TOKEN}"
          fi
          if [[ -n "''${CLOUDFLARE_ACCOUNT_ID:-}" && -z "''${CF_ACCOUNT_ID:-}" ]]; then
            export CF_ACCOUNT_ID="''${CLOUDFLARE_ACCOUNT_ID}"
          fi
          if [[ -n "''${CLOUDFLARE_ZONE_ID:-}" && -z "''${CF_ZONE_ID:-}" ]]; then
            export CF_ZONE_ID="''${CLOUDFLARE_ZONE_ID}"
          fi
          shift
          exec flarectl "$@"
          ;;
        *)
          echo "Unknown command: $1" >&2
          echo "Run: cfctl help" >&2
          exit 2
          ;;
      esac
    '';
  };
in
{
  config = lib.mkMerge [
    {
      environment.systemPackages = with pkgs; [
        cfctl
        flarectl
        wrangler
      ];
    }

    (lib.mkIf cfg.publicTunnel.enable {
      # Tailscale's exit-node policy is consulted before the main routing table.
      # Mullvad does not pass cloudflared's TCP/UDP 7844 traffic, so send only
      # Cloudflare's documented tunnel edge ranges through the normal uplink.
      systemd.services.cloudflared-direct-egress = {
        description = "Route Cloudflare Tunnel edge traffic outside the Tailscale exit node";
        wantedBy = [ "multi-user.target" ];
        wants = [ "network-online.target" ];
        after = [
          "network-online.target"
          "tailscaled.service"
        ];
        before = [ cloudflaredTunnelUnit ];

        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };

        script = ''
          ${ip} -4 rule delete priority 5200 to 198.41.192.0/24 table main 2>/dev/null || true
          ${ip} -4 rule delete priority 5201 to 198.41.200.0/24 table main 2>/dev/null || true
          ${ip} -4 rule add priority 5200 to 198.41.192.0/24 table main
          ${ip} -4 rule add priority 5201 to 198.41.200.0/24 table main
        '';

        preStop = ''
          ${ip} -4 rule delete priority 5200 to 198.41.192.0/24 table main 2>/dev/null || true
          ${ip} -4 rule delete priority 5201 to 198.41.200.0/24 table main 2>/dev/null || true
        '';
      };

      systemd.services."cloudflared-tunnel-${cfg.publicTunnel.tunnelId}" = {
        requires = [ "cloudflared-direct-egress.service" ];
        after = [ "cloudflared-direct-egress.service" ];
      };

      services.cloudflared = {
        enable = true;
        tunnels.${cfg.publicTunnel.tunnelId} = {
          credentialsFile = config.sops.secrets."cloudflared-tunnel.json".path;
          default = "http_status:404";
          ingress = {
            "${cfg.domain}" = "http://127.0.0.1:8080";
            "*.${cfg.domain}" = "http://127.0.0.1:8080";
          };
        };
      };

      assertions = [
        {
          assertion = cfg.secrets.enable;
          message = "homelab.publicTunnel.enable requires homelab.secrets.enable for the tunnel credentials file.";
        }
        {
          assertion = cfg.publicTunnel.tunnelId != null;
          message = "homelab.publicTunnel.tunnelId must be set to the Cloudflare Tunnel UUID.";
        }
      ];
    })
  ];
}
