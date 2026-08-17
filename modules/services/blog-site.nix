{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.blogSite;
  homelab = config.homelab;
  source = homelab.paths.blogSiteSource;
  state = homelab.paths.blogSiteState;
  previewState = "${state}-preview";
  editorUrl = "https://lab.${homelab.internalDomain}";
  publicUrl = "https://blog.${homelab.domain}";
  previewUrl = "https://blog.${homelab.internalDomain}";
  quarto = pkgs.callPackage ./quarto-bin.nix { };
  python = pkgs.python3.withPackages (ps: [
    ps.aiohttp
    ps.ipykernel
    ps.jupyter-client
    ps.nbclient
    ps.nbformat
    ps.pyyaml
  ]);
  blogctl = pkgs.writeShellApplication {
    name = "blogctl";
    runtimeInputs = [
      quarto
      pkgs.rsync
      python
    ];
    text = ''
      export BLOG_SOURCE=${lib.escapeShellArg source}
      export BLOG_STATE=${lib.escapeShellArg state}
      export BLOG_PREVIEW_STATE=${lib.escapeShellArg previewState}
      export BLOG_RESUME=${lib.escapeShellArg homelab.paths.resumePdf}
      export BLOG_QUARTO=${lib.escapeShellArg "${quarto}/bin/quarto"}
      export BLOG_RSYNC=${lib.escapeShellArg "${pkgs.rsync}/bin/rsync"}
      exec ${python}/bin/python3 ${../../scripts/blog-admin.py} "$@"
    '';
  };
in
{
  options.homelab.blogSite = {
    enable = lib.mkEnableOption "public Quarto notebook blog with private administration";
    adminPort = lib.mkOption {
      type = lib.types.port;
      default = 8792;
      description = "Loopback port for the blog administration service.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      blogctl
      quarto
    ];

    systemd.tmpfiles.rules = [
      "d ${state} 0755 rishabh users - -"
      "d ${previewState} 0755 rishabh users - -"
    ];

    systemd.services.blog-admin = {
      description = "Private Quarto blog administration";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];
      environment.XDG_CACHE_HOME = "/var/cache/blog-admin";
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        WorkingDirectory = source;
        ExecStart = "${blogctl}/bin/blogctl serve --assets ${../../blog-admin} --editor-url ${editorUrl} --public-url ${publicUrl} --preview-url ${previewUrl} --port ${toString cfg.adminPort}";
        Restart = "on-failure";
        RestartSec = "5s";
        UMask = "0022";
        NoNewPrivileges = true;
        PrivateTmp = true;
        CacheDirectory = "blog-admin";
        CacheDirectoryMode = "0700";
        ProtectHome = "read-only";
        ProtectSystem = "strict";
        ReadWritePaths = [
          source
          state
          previewState
        ];
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
          "AF_UNIX"
        ];
      };
    };

    homelab.routes.blog = {
      host = "blog";
      visibility = "public";
      caddyConfig = ''
        encode zstd gzip
        @resumeAliases path /resume.pdf /Resume.pdf
        redir @resumeAliases /rishabh-goel-resume.pdf 308
        root * ${state}
        file_server
      '';
      description = "Public Quarto notebook blog";
    };

    homelab.routes.blog-admin = {
      host = "blog";
      visibility = "internal";
      caddyConfig = ''
        encode zstd gzip
        handle /admin* {
          reverse_proxy http://127.0.0.1:${toString cfg.adminPort}
        }
        handle {
          root * ${previewState}
          file_server
        }
      '';
      description = "Private blog administration and internal copy";
    };

    homelab.routes.home = {
      host = "home";
      visibility = "public";
      redirectTo = "${publicUrl}{uri}";
      description = "Legacy personal site redirect to the public blog";
    };

    homelab.routes.apex = {
      host = "@";
      visibility = "public";
      redirectTo = "${publicUrl}{uri}";
      description = "Apex redirect to the public blog";
    };

    homelab.routes.www = {
      host = "www";
      visibility = "public";
      redirectTo = "${publicUrl}{uri}";
      description = "www redirect to the public blog";
    };

    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.blogSite.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
