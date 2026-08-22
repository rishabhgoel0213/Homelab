{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (lib)
    filterAttrs
    mapAttrs
    mapAttrs'
    mkIf
    nameValuePair
    optionalString
    ;

  cfg = config.homelab;

  hasDot = value: builtins.match ".*\\..*" value != null;

  routeFqdn =
    route:
    if route.fqdn != null then
      route.fqdn
    else if route.host == "@" then
      cfg.domain
    else if hasDot route.host then
      route.host
    else if route.visibility == "internal" then
      "${route.host}.${cfg.internalDomain}"
    else
      "${route.host}.${cfg.domain}";

  routeSiteAddress =
    route:
    let
      fqdn = routeFqdn route;
    in
    if route.visibility == "internal" then fqdn else "http://${fqdn}:8080";

  routeConfig =
    route:
    let
      body =
        if route.caddyConfig != null then
          route.caddyConfig
        else if route.redirectTo != null then
          ''
            redir ${route.redirectTo} ${toString route.redirectStatus}
          ''
        else if route.upstream != null then
          ''
            encode zstd gzip
            reverse_proxy ${route.upstream}${
              optionalString (
                route.upstreamHostHeader != null
              ) " {\n              header_up Host ${route.upstreamHostHeader}\n            }"
            }
          ''
        else if route.root != null then
          ''
            encode zstd gzip
            root * ${route.root}
            try_files {path} /index.html
            file_server
          ''
        else if route.response != null then
          ''
            respond ${builtins.toJSON route.response} ${toString route.status}
          ''
        else
          ''
            respond "Route has no upstream, root, or response configured." 502
          '';
    in
    body + optionalString (route.extraConfig != "") "\n${route.extraConfig}";

  enabledRoutes = filterAttrs (_: route: route.enable) cfg.routes;

  mkVhost =
    name: route:
    nameValuePair "homelab-route-${name}" {
      hostName = routeSiteAddress route;
      useACMEHost = if route.visibility == "internal" && cfg.acme.enable then cfg.domain else null;
      extraConfig = routeConfig route;
    };

  publicCatchalls = {
    "homelab-public-wildcard-catchall" = {
      hostName = "http://*.${cfg.domain}:8080";
      extraConfig = ''
        respond "No public route is published for this hostname." 404
      '';
    };
  };

  internalCatchalls =
    if cfg.acme.enable then
      {
        "homelab-internal-wildcard-catchall" = {
          hostName = "*.${cfg.internalDomain}";
          useACMEHost = cfg.domain;
          extraConfig = ''
            respond "No internal route is published for this hostname." 404
          '';
        };
      }
    else
      { };
in
{
  config = {
    services.caddy = {
      enable = true;
      virtualHosts = publicCatchalls // internalCatchalls // (mapAttrs' mkVhost enabledRoutes);
    };

    security.acme = mkIf cfg.acme.enable {
      acceptTerms = true;
      defaults.email = cfg.acme.email;

      certs.${cfg.domain} = {
        domain = cfg.domain;
        extraDomainNames = [
          "*.${cfg.domain}"
          "*.${cfg.internalDomain}"
        ];
        dnsProvider = "cloudflare";
        environmentFile = config.sops.secrets."cloudflare-dns.env".path;
        group = config.services.caddy.group;
        reloadServices = [ "caddy.service" ];
      };
    };

    homelab.routeTable = mapAttrs (_: route: {
      inherit (route) visibility description;
      host = routeFqdn route;
      target =
        if route.caddyConfig != null then
          "custom"
        else if route.redirectTo != null then
          "redirect:${toString route.redirectStatus}:${route.redirectTo}"
        else if route.upstream != null then
          route.upstream
        else if route.root != null then
          route.root
        else
          "response:${toString route.status}";
    }) enabledRoutes;

    assertions = [
      {
        assertion = !cfg.acme.enable || cfg.secrets.enable;
        message = "homelab.acme.enable requires homelab.secrets.enable for Cloudflare DNS credentials.";
      }
    ];
  };
}
