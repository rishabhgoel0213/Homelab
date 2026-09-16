{ config, pkgs, ... }:
let
  inherit (config) homelab;
in
{
  systemd.services.project-catalog = {
    description = "Private read-only project category feeds for Zen";
    wantedBy = [ "multi-user.target" ];
    environment = {
      PROJECTS_ROOT = homelab.paths.projectsRoot;
      PROJECTCTL_SOURCE = "${./bin/projectctl.py}";
      PROJECTCTL_JUPYTER_URL = "https://lab.${homelab.internalSubdomain}.${homelab.domain}";
      PROJECTCTL_JUPYTER_ROOT = "/";
      PYTHONDONTWRITEBYTECODE = "1";
    };
    serviceConfig = {
      ExecStart = "${pkgs.python3}/bin/python3 ${./bin/catalog.py} ${./categories.json}";
      User = "rishabh";
      Group = "users";
      Restart = "on-failure";
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = "read-only";
      PrivateTmp = true;
      PrivateDevices = true;
      CapabilityBoundingSet = "";
      RestrictAddressFamilies = [
        "AF_INET"
        "AF_UNIX"
      ];
      IPAddressDeny = "any";
      IPAddressAllow = "localhost";
      UMask = "0077";
    };
  };
  homelab.routes.projects = {
    enable = true;
    host = "projects";
    visibility = "internal";
    upstream = "http://127.0.0.1:8796";
    description = "Private project category feeds";
  };
}
