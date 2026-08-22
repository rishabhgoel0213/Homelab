{ config, lib, pkgs, ... }:

let
  cfg = config.homelab;

  tsctl = pkgs.writeShellApplication {
    name = "tsctl";
    runtimeInputs = with pkgs; [
      coreutils
      curl
      jq
    ];
    text = ''
      set -euo pipefail

      env_file="''${TAILSCALE_ENV_FILE:-/run/secrets/tailscale-oauth.env}"

      load_env() {
        if [[ -r "$env_file" ]]; then
          set -a
          # shellcheck disable=SC1090
          . "$env_file"
          set +a
        fi
      }

      need_credentials() {
        load_env
        if [[ -z "''${TAILSCALE_OAUTH_CLIENT_ID:-}" || -z "''${TAILSCALE_OAUTH_CLIENT_SECRET:-}" ]]; then
          echo "Missing TAILSCALE_OAUTH_CLIENT_ID or TAILSCALE_OAUTH_CLIENT_SECRET in $env_file" >&2
          exit 1
        fi
      }

      access_token() {
        local requested_scope="''${1:-}"
        need_credentials
        args=(
          --fail-with-body
          --silent
          --show-error
          --request POST
          --data-urlencode "client_id=''${TAILSCALE_OAUTH_CLIENT_ID}"
          --data-urlencode "client_secret=''${TAILSCALE_OAUTH_CLIENT_SECRET}"
        )
        if [[ -n "$requested_scope" ]]; then
          args+=(--data-urlencode "scope=$requested_scope")
        fi
        curl "''${args[@]}" "https://api.tailscale.com/api/v2/oauth/token" | jq -r '.access_token'
      }

      api() {
        method="$1"
        path="$2"
        body="''${3:-}"
        scope="''${TAILSCALE_API_SCOPE:-}"
        if [[ -z "$scope" ]]; then
          if [[ "$method" == "GET" ]]; then
            scope="''${TAILSCALE_OAUTH_READ_SCOPES:-''${TAILSCALE_OAUTH_SCOPES:-dns:read}}"
          else
            scope="''${TAILSCALE_OAUTH_WRITE_SCOPES:-dns:write}"
          fi
        fi
        token="$(access_token "$scope")"

        if [[ -n "$body" ]]; then
          curl --fail-with-body --silent --show-error \
            --request "$method" \
            --header "Authorization: Bearer $token" \
            --header "Content-Type: application/json" \
            --data "$body" \
            "https://api.tailscale.com/api/v2$path"
        else
          curl --fail-with-body --silent --show-error \
            --request "$method" \
            --header "Authorization: Bearer $token" \
            --header "Content-Type: application/json" \
            "https://api.tailscale.com/api/v2$path"
        fi
      }

      tailnet_path() {
        local suffix="$1"
        local tailnet="''${TAILSCALE_TAILNET:--}"
        printf '/tailnet/%s%s' "$tailnet" "$suffix"
      }

      case "''${1:-help}" in
        help|-h|--help)
          cat <<'EOF'
tsctl: Tailscale API helper

Usage:
  tsctl verify
  tsctl devices
  tsctl dns-nameservers
  tsctl dns-preferences
  tsctl dns-searchpaths
  tsctl api METHOD /path [json-body]

Reads credentials from:
  /run/secrets/tailscale-oauth.env

Expected variables:
  TAILSCALE_OAUTH_CLIENT_ID
  TAILSCALE_OAUTH_CLIENT_SECRET
  TAILSCALE_OAUTH_READ_SCOPES=dns:read
  TAILSCALE_OAUTH_WRITE_SCOPES=dns:write
  TAILSCALE_TAILNET=-
EOF
          ;;
        verify)
          api GET "$(tailnet_path /dns/nameservers)" | jq .
          ;;
        devices)
          api GET "$(tailnet_path /devices)" | jq .
          ;;
        dns-nameservers)
          api GET "$(tailnet_path /dns/nameservers)" | jq .
          ;;
        dns-preferences)
          api GET "$(tailnet_path /dns/preferences)" | jq .
          ;;
        dns-searchpaths)
          api GET "$(tailnet_path /dns/searchpaths)" | jq .
          ;;
        api)
          if [[ $# -lt 3 || $# -gt 4 ]]; then
            echo "usage: tsctl api METHOD /path [json-body]" >&2
            exit 2
          fi
          shift
          api "$@" | jq .
          ;;
        *)
          echo "Unknown command: $1" >&2
          echo "Run: tsctl help" >&2
          exit 2
          ;;
      esac
    '';
  };
in
{
  config = lib.mkIf cfg.secrets.enable {
    environment.systemPackages = [ tsctl ];
  };
}
