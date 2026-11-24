set shell := ["bash", "-eo", "pipefail", "-c"]

host := env_var_or_default("HOST", "nixos-pc")
darwin_host := env_var_or_default("DARWIN_HOST", "macbook")

default:
    @just --list

check:
    nix flake check --impure

build:
    tools/admin nixos-rebuild build --no-link --impure --flake .#{{host}}

test:
    tools/admin nixos-rebuild test --impure --flake .#{{host}}

deploy:
    tools/deploy

switch:
    @test "$PWD" = /srv/ops || { echo 'Use just deploy from ~/Projects/Homelab.' >&2; exit 1; }
    tools/admin nixos-rebuild switch --impure --flake .#{{host}}

rollback:
    tools/admin nixos-rebuild switch --rollback

darwin-eval:
    nix eval --impure --raw '.#darwinConfigurations.{{darwin_host}}.system.drvPath'

# Builds one isolated target on the server or locally on the Mac without activation.
darwin-build target="macbook-system":
    hosts/macbook/build "{{target}}" "{{darwin_host}}"

# Requires MACBOOK_DEPLOY_CONFIRM=deploy. Darwin-only work builds locally on
# the Mac before the exact store path is activated over Tailscale SSH.
darwin-deploy:
    hosts/macbook/deploy "{{darwin_host}}"

# Builds, signs, and copies Mac application payloads without activation.
darwin-copy-apps:
    hosts/macbook/copy-apps

# Rebuilds and roots the signed Mac payload inputs on the server without Mac contact.
darwin-prepare-artifacts:
    bash hosts/macbook/prepare-artifacts

routes:
    nix eval --impure --json .#nixosConfigurations.{{host}}.config.homelab.routeTable | jq .

route-add name visibility upstream:
    routes/bin/add "{{name}}" "{{visibility}}" "{{upstream}}"

route-remove name:
    routes/bin/remove "{{name}}"

logs service:
    journalctl -u "{{service}}" -f

status:
    systemctl --no-pager --failed
    systemctl --no-pager status caddy.service || true
    systemctl --no-pager status tailscaled.service || true
    systemctl --no-pager status docker.service || true

project-list:
    projectctl list

project-create name:
    projectctl create "{{name}}"

project-show project:
    projectctl show "{{project}}"

project-session project harness="codex":
    projectctl session "{{project}}" "{{harness}}"

project-jupyter project:
    projectctl jupyter "{{project}}"

project-sync-enable project target="macbook":
    projectctl sync enable "{{project}}" --target "{{target}}"

project-sync-disable project target="macbook":
    projectctl sync disable "{{project}}" --target "{{target}}"

project-sync-status project:
    projectctl sync status "{{project}}"

project-sync-deploy target="macbook":
    projectctl sync deploy "{{target}}"

backup-now:
    @echo "Backrest owns backup runs now. Open https://backups.internal.therealrishabh.com and run the plan from the UI."

recovery-kit:
    tools/admin tools/recovery/create-vps-recovery-kit

codex-bootstrap:
    components/codex/bin/bootstrap

codex-update:
    nix shell --inputs-from . nixpkgs#git nixpkgs#jq nixpkgs#perl --command components/codex/bin/update

codex-auto-update:
    tools/admin components/codex/bin/auto-update

# Publish the already-pinned signed Mac CLI; does not contact the Mac.
codex-publish-mac:
    tools/admin components/codex/bin/publish-mac

codex-store-auth:
    components/codex/bin/store-auth

codex-migrate-state:
    components/codex/bin/migrate-state

codex-prune-user-install:
    components/codex/bin/prune-user-install

secrets-edit:
    tools/secrets/edit

secrets-check:
    tools/secrets/check

bitwarden-promote:
    nix shell --inputs-from . nixpkgs#bitwarden-cli nixpkgs#fzf --command tools/secrets/promote-bitwarden-secret

cloudflare-store-token:
    components/cloudflare/bin/store-token

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
    components/tailscale/bin/store-oauth

tailscale-verify:
    tsctl verify

tailscale-devices:
    tsctl devices

tailscale-dns:
    tsctl dns-nameservers

tailscale-split-dns:
    tsctl api GET /tailnet/-/dns/split-dns

tailscale-apply-internal-dns:
    components/tailscale/bin/configure-internal-dns

mullvad-is-connected:
    curl https://am.i.mullvad.net/connected

canvas-doctor:
    canvas-bridge doctor

canvas-pair:
    canvas-bridge pair

canvas-status:
    canvas-bridge status

canvas-sync:
    canvas-bridge sync

matrix-doctor:
    components/matrix/bin/doctor

matrix-user-add username="rishabh":
    tools/admin matrix-synapse-register_new_matrix_user --user "{{username}}" --no-admin

matrix-gmessages-store-secrets:
    nix shell --inputs-from . nixpkgs#openssl --command components/matrix/bin/store-gmessages-secrets

matrix-whatsapp-logs:
    journalctl -u mautrix-whatsapp.service -f

matrix-gmessages-logs:
    journalctl -u mautrix-gmessages.service -f

matrix-imessage-proxy-logs:
    journalctl -u mautrix-wsproxy.service -f

matrix-imessage-export-config:
    @echo "This writes a secret-bearing Mac config to stdout; redirect it to a mode-0600 file." >&2
    tools/admin matrix-imessage-export-config

t3code-doctor:
    components/t3code/bin/doctor

t3code-pair:
    t3code pair --base-dir /srv/state/t3code --ttl 10m

t3code-status:
    systemctl --no-pager status t3code.service

t3code-logs:
    journalctl -u t3code.service -f

t3code-update target="nightly":
    components/t3code/bin/update "{{target}}"

t3code-auto-update:
    components/t3code/bin/auto-update

t3code-publish-mac:
    tools/admin components/t3code/bin/publish-mac

qwen-image-fetch:
    tools/admin systemctl start qwen-image-2.1-download.service

qwen-image-use:
    tools/admin systemctl start qwen-image-2.1.service
    curl --fail --silent --show-error --retry 120 --retry-delay 1 --retry-all-errors http://127.0.0.1:8188/system_stats >/dev/null

qwen-image-stop:
    tools/admin systemctl stop qwen-image-2.1.service

github-profile-sync:
    tools/sync-github-profile

claude-update:
    components/claude/bin/update

claude-auto-update:
    tools/admin components/claude/bin/auto-update

claude-publish-mac:
    tools/admin components/claude/bin/publish-mac

antigravity-update:
    components/antigravity/bin/update

antigravity-auto-update:
    tools/admin components/antigravity/bin/auto-update

antigravity-publish-mac:
    tools/admin components/antigravity/bin/publish-mac
