{ config, lib, ... }:

let
  inherit (lib) mkEnableOption mkOption types;
in
{
  options.homelab = {
    domain = mkOption {
      type = types.str;
      description = "Base public domain for this server.";
    };

    internalSubdomain = mkOption {
      type = types.str;
      default = "internal";
      description = "Subdomain used for tailnet-only applications.";
    };

    internalDomain = mkOption {
      type = types.str;
      readOnly = true;
      description = "Fully qualified internal domain.";
    };

    tailnetIp = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Stable Tailscale IPv4 address for this host.";
    };

    tailnetIpv6 = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Stable Tailscale IPv6 address for this host.";
    };

    paths = {
      userHome = mkOption {
        type = types.str;
        default = "/home/rishabh";
        description = "Primary user's home directory.";
      };
      opsRoot = mkOption {
        type = types.str;
        default = "/srv/ops";
        description = "Infrastructure repository root.";
      };
      stateRoot = mkOption {
        type = types.str;
        default = "/srv/state";
        description = "Durable service state root.";
      };
      agentCockpit = mkOption {
        type = types.str;
        default = "/home/rishabh/Agent";
        description = "Generated instruction-only landing directory for interactive agents.";
      };
      agentStateRoot = mkOption {
        type = types.str;
        default = "/srv/state/agents";
        description = "Persistent harness-neutral agent metadata root.";
      };
      agentWorkRoot = mkOption {
        type = types.str;
        default = "/var/tmp/agent-work";
        description = "Manifest-managed root for expiring ad hoc agent work.";
      };
      secretsFile = mkOption {
        type = types.path;
        default = /home/rishabh/.config/homelab/secrets.yaml;
        description = "Local encrypted SOPS secrets file.";
      };
      publicSiteSource = mkOption {
        type = types.str;
        default = "/home/rishabh/Projects/public-site";
        description = "Editable public site source directory.";
      };
      publicSiteState = mkOption {
        type = types.str;
        default = "/srv/state/public-site";
        description = "Deployed public site directory served by Caddy.";
      };
      resumePdf = mkOption {
        type = types.str;
        default = "/home/rishabh/Documents/resume/Resume.pdf";
        description = "Canonical resume PDF copied into the deployed public site.";
      };
      githubProfileReadme = mkOption {
        type = types.str;
        default = "/home/rishabh/Documents/github-profile/README.md";
        description = "Managed source README for the public GitHub profile repository.";
      };
      remoteShare = mkOption {
        type = types.str;
        default = "/home/rishabh/Remote";
        description = "User-owned directory exported over SMB.";
      };
      codexHome = mkOption {
        type = types.str;
        default = "/srv/state/codex";
        description = "Managed Codex runtime home.";
      };
      codexConfigSource = mkOption {
        type = types.str;
        default = "/srv/ops/codex/config.toml";
        description = "Default Codex config source managed by the ops repository.";
      };
      codexAgentsSource = mkOption {
        type = types.str;
        default = "/srv/ops/codex/AGENTS.md";
        description = "Global Codex guidance source managed by the ops repository.";
      };
      codexPluginRoot = mkOption {
        type = types.str;
        default = "/srv/ops/codex/plugins";
        description = "Repo-local Codex plugin source root.";
      };
    };

    acme = {
      enable = mkEnableOption "wildcard ACME certificates through Cloudflare DNS";
      email = mkOption {
        type = types.str;
        description = "Email address used for ACME registration.";
      };
    };

    secrets.enable = mkEnableOption "sops-nix managed server secrets";

    publicTunnel = {
      enable = mkEnableOption "Cloudflare Tunnel public wildcard ingress";
      tunnelId = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Cloudflare Tunnel UUID.";
      };
    };

    privateDns.enable = mkEnableOption "CoreDNS wildcard DNS for internal tailnet apps";

    remotePhone.enable = mkEnableOption "bounded Remote Phone microphone capture and local transcription";

    backrest = {
      enable = mkEnableOption "Backrest private restic web UI";
      repository = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Backrest Restic repository, for example an sftp: URL or local path.";
      };
      sshTarget = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Optional SSH target for Backrest SFTP repositories, for example u123456@u123456.your-storagebox.de.";
      };
      sshPort = mkOption {
        type = types.port;
        default = 23;
        description = "SSH port for the Backrest SFTP command. Hetzner Storage Boxes commonly use port 23.";
      };
      image = mkOption {
        type = types.str;
        default = "garethgeorge/backrest@sha256:9c9966b5c285ec791a6b06cb4545fa0247424d05442e12f9558b4322d9f8a15f";
        description = "Pinned Backrest container image.";
      };
    };

    vaultwarden.enable = mkEnableOption "Vaultwarden private password vault";
    eden.enable = mkEnableOption "Eden private Switch emulator desktop";
    jellyfin.enable = mkEnableOption "Jellyfin private media server";
    syncthing.enable = mkEnableOption "Syncthing private file sync";
    samba.enable = mkEnableOption "Private SMB file share";

    routes = mkOption {
      default = { };
      description = "Declarative HTTP route registry.";
      type = types.attrsOf (
        types.submodule (
          { name, ... }:
          {
            options = {
              enable = mkOption {
                type = types.bool;
                default = true;
                description = "Whether this route is published.";
              };

              host = mkOption {
                type = types.str;
                default = name;
                description = "Subdomain label, @ for the apex, or a full hostname.";
              };

              fqdn = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Optional fully qualified hostname override.";
              };

              visibility = mkOption {
                type = types.enum [
                  "internal"
                  "public"
                ];
                default = "internal";
                description = "Which ingress lane serves this route.";
              };

              upstream = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Reverse proxy upstream, such as http://127.0.0.1:3000.";
              };

              upstreamHostHeader = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Optional Host header value to send to the reverse proxy upstream.";
              };

              redirectTo = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Redirect target, such as https://home.example.com{uri}.";
              };

              redirectStatus = mkOption {
                type = types.int;
                default = 308;
                description = "HTTP status code used when redirectTo is set.";
              };

              root = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Static file root served by Caddy.";
              };

              response = mkOption {
                type = types.nullOr types.str;
                default = null;
                description = "Static response body for simple placeholder routes.";
              };

              status = mkOption {
                type = types.int;
                default = 200;
                description = "HTTP status for response routes.";
              };

              extraConfig = mkOption {
                type = types.lines;
                default = "";
                description = "Extra Caddy directives appended to this route.";
              };

              description = mkOption {
                type = types.str;
                default = "";
                description = "Human-readable route note.";
              };
            };
          }
        )
      );
    };

    routeTable = mkOption {
      type = types.attrs;
      default = { };
      description = "Computed route table for status commands.";
    };
  };

  config.homelab.internalDomain = "${config.homelab.internalSubdomain}.${config.homelab.domain}";
}
