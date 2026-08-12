set shell := ["bash", "-eo", "pipefail", "-c"]

host := env_var_or_default("HOST", "nixos-pc")

default:
    @just --list

check:
    nix flake check --impure

build:
    sudo nixos-rebuild build --no-link --impure --flake .#{{host}}

test:
    sudo nixos-rebuild test --impure --flake .#{{host}}

switch:
    sudo nixos-rebuild switch --impure --flake .#{{host}}

rollback:
    sudo nixos-rebuild switch --rollback

routes:
    nix eval --impure --json .#nixosConfigurations.{{host}}.config.homelab.routeTable | jq .

route-add name visibility upstream:
    scripts/add-route "{{name}}" "{{visibility}}" "{{upstream}}"

route-remove name:
    scripts/remove-route "{{name}}"

logs service:
    journalctl -u "{{service}}" -f

status:
    systemctl --no-pager --failed
    systemctl --no-pager status caddy.service || true
    systemctl --no-pager status tailscaled.service || true
    systemctl --no-pager status docker.service || true

backup-now:
    @echo "Backrest owns backup runs now. Open https://backups.internal.therealrishabh.com and run the plan from the UI."

public-site-deploy:
    scripts/public-site-deploy

codex-bootstrap:
    scripts/codex-bootstrap

codex-update:
    nix shell --inputs-from . nixpkgs#git nixpkgs#jq nixpkgs#perl --command scripts/update-codex

codex-auto-update:
    sudo scripts/codex-auto-update

pi-update:
    nix shell --inputs-from . nixpkgs#git nixpkgs#jq nixpkgs#perl --command scripts/update-pi

pi-auto-update:
    sudo scripts/pi-auto-update

codex-store-auth:
    scripts/codex-store-auth

codex-migrate-state:
    scripts/codex-migrate-state

codex-prune-user-install:
    scripts/codex-prune-user-install

agent-index:
    agent index

agent-work:
    agent work

agent-gc:
    agent gc

secrets-edit:
    scripts/secrets-edit

secrets-check:
    scripts/secrets-check

bitwarden-promote:
    nix shell --inputs-from . nixpkgs#bitwarden-cli nixpkgs#fzf --command scripts/promote-bitwarden-secret

cloudflare-store-token:
    scripts/store-cloudflare-token

cloudflare-login:
    cfctl tunnel-login

cloudflare-create-tunnel name:
    cfctl tunnel-create "{{name}}"

cloudflare-verify:
    cfctl verify

cloudflare-zones:
    cfctl zones

cloudflare-dns:
    cfctl dns

tailscale-ip:
    tailscale ip -4

tailscale-store-oauth:
    scripts/store-tailscale-oauth

tailscale-verify:
    tsctl verify

tailscale-devices:
    tsctl devices

tailscale-dns:
    tsctl dns-nameservers

tailscale-split-dns:
    tsctl api GET /tailnet/-/dns/split-dns

tailscale-apply-internal-dns:
    scripts/configure-tailscale-internal-dns

mullvad-is-connected:
    curl https://am.i.mullvad.net/connected

remote-phone-doctor:
    remote-phone-mic doctor

remote-phone-check:
    remote-phone-mic check

canvas-doctor:
    canvas-bridge doctor

canvas-pair:
    canvas-bridge pair

canvas-status:
    canvas-bridge status

canvas-sync:
    canvas-bridge sync

matrix-doctor:
    scripts/matrix-doctor

matrix-user-add username="rishabh":
    sudo matrix-synapse-register_new_matrix_user --user "{{username}}" --no-admin

matrix-whatsapp-logs:
    journalctl -u mautrix-whatsapp.service -f

matrix-instagram-logs:
    journalctl -u mautrix-instagram.service -f

matrix-imessage-proxy-logs:
    journalctl -u mautrix-wsproxy.service -f

matrix-imessage-export-config:
    @echo "This writes a secret-bearing Mac config to stdout; redirect it to a mode-0600 file." >&2
    sudo matrix-imessage-export-config

matrix-pi-logs:
    journalctl -u pi-courier.service -f

t3code-doctor:
    scripts/t3code-doctor

t3code-pair:
    t3code pair --base-dir /srv/state/t3code --ttl 10m

t3code-status:
    systemctl --no-pager status t3code.service

t3code-logs:
    journalctl -u t3code.service -f

t3code-mobile-bootstrap:
    scripts/build-t3code-mobile-bootstrap

local-model-fetch model:
    sudo systemctl start "$(nix eval --raw --impure '.#nixosConfigurations.{{host}}.config.homelab.pi.localModels."{{model}}".fetchUnit')"

local-model-use model:
    sudo systemctl start "$(nix eval --raw --impure '.#nixosConfigurations.{{host}}.config.homelab.pi.localModels."{{model}}".serviceUnit')"
    curl --fail --silent --show-error --retry 600 --retry-delay 1 --retry-all-errors "$(nix eval --raw --impure '.#nixosConfigurations.{{host}}.config.homelab.pi.localModels."{{model}}".healthUrl')" >/dev/null
    local-model-doctor "{{model}}"

local-model-doctor model="":
    local-model-doctor "{{model}}"

github-profile-sync:
    scripts/sync-github-profile
