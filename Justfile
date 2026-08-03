set shell := ["bash", "-eo", "pipefail", "-c"]

host := env_var_or_default("HOST", "nixos-pc")

default:
    @just --list

check:
    nix flake check --impure

build:
    sudo nixos-rebuild build --no-build-output --impure --flake .#{{host}}

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

codex-store-auth:
    scripts/codex-store-auth

codex-migrate-state:
    scripts/codex-migrate-state

codex-prune-user-install:
    scripts/codex-prune-user-install

codex-desktop *args:
    codex-desktop {{args}}

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

github-profile-sync:
    scripts/sync-github-profile
