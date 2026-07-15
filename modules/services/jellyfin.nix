{ config, lib, ... }:

let
  cfg = config.homelab;
in
{
  config = lib.mkIf cfg.jellyfin.enable {
    services.jellyfin = {
      enable = true;
      user = "rishabh";
      group = "users";
      dataDir = "${cfg.paths.stateRoot}/jellyfin";
      cacheDir = "${cfg.paths.stateRoot}/jellyfin/cache";
      openFirewall = false;

      hardwareAcceleration = {
        enable = true;
        type = "nvenc";
        device = "/dev/dri/renderD128";
      };
      forceEncodingConfig = true;
      transcoding = {
        enableHardwareEncoding = true;
        hardwareDecodingCodecs = {
          h264 = true;
          hevc = true;
          hevc10bit = true;
          mpeg2 = true;
          vc1 = true;
          vp8 = true;
          vp9 = true;
          av1 = true;
        };
        hardwareEncodingCodecs.hevc = true;
      };
    };

    # Jellyfin needs to traverse rishabh's private home directory to discover
    # media, but it should never be able to modify the source files.
    systemd.services.jellyfin.serviceConfig.ProtectHome = "read-only";

    homelab.routes.media = {
      enable = true;
      host = "media";
      visibility = "internal";
      upstream = "http://127.0.0.1:8096";
      description = "Jellyfin private media server";
    };
  };
}
