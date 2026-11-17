{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.homelab;
  apk = pkgs.fetchurl {
    url = "https://github.com/wa2c/cifs-documents-provider/releases/download/Ver.2.4.0/CIFSDocumentsProvider-2.4.0-release.apk";
    hash = "sha256-WrawP62FZMpYuo2kHlXVOq8pl/hMu4ZecZUq4l75cMU=";
  };
  python = pkgs.python3.withPackages (ps: [ ps.cryptography ]);
  downloads = pkgs.runCommand "homelab-cifs-mobile" { nativeBuildInputs = [ python ]; } ''
    mkdir -p "$out"
    ln -s ${apk} "$out/cifs-documents-provider.apk"
    python ${./mobile-profile.py} ${lib.escapeShellArg cfg.tailnetIp} > "$out/homelab.cifs"
    cp ${./mobile.html} "$out/index.html"
  '';
in
{
  config = lib.mkIf cfg.samba.enable {
    homelab.routes.smb-mobile = {
      enable = true;
      host = "smb";
      visibility = "internal";
      description = "Android SMB provider and Homelab connection profile";
      caddyConfig = ''
        @outsideTailnet not remote_ip 100.64.0.0/10 fd7a:115c:a1e0::/48
        respond @outsideTailnet "Tailnet access required." 403
        root * ${downloads}
        header Cache-Control "no-store"
        @apk path /cifs-documents-provider.apk
        header @apk {
          Content-Type application/vnd.android.package-archive
          Content-Disposition "attachment; filename=cifs-documents-provider.apk"
        }
        @profile path /homelab.cifs
        header @profile {
          Content-Type application/octet-stream
          Content-Disposition "attachment; filename=homelab.cifs"
        }
        file_server
      '';
    };
  };
}
