# Bitwarden To Sops

Use `just bitwarden-promote` to copy one selected Bitwarden/Vaultwarden field
into `/home/rishabh/.config/homelab/secrets.yaml`.

The tool:

- uses the local `bw` CLI and prompts you to log in or unlock
- lists vault item labels through `fzf`
- lets you select one field, such as `login.password`, `notes`, or a custom field
- optionally reveals that selected value in the terminal
- writes only that selected value to one sops key

By default it points `bw` at:

```text
https://vault.internal.therealrishabh.com
```

Override that for one run with:

```bash
BW_SERVER_URL=https://vault.example.com just bitwarden-promote
```

Good candidates to promote are automation-specific secrets such as API tokens,
SSH private keys for service accounts, or OAuth client secrets. Do not sync the
whole vault into sops.
