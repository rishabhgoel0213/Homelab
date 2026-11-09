{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  cfg = config.homelab.t3code;
  stateDir = homelab.paths.t3codeState;
  package = pkgs.callPackage ./package.nix { };
  androidSdk = (pkgs.androidenv.composeAndroidPackages {
    platformVersions = [ "35" ];
    buildToolsVersions = [ "35.0.0" ];
    includeEmulator = true;
    includeSystemImages = true;
    systemImageTypes = [ "google_apis" ];
    abiVersions = [ "x86_64" ];
  }).androidsdk;
  mobileIndex = pkgs.writeText "t3code-nightly-download.html" ''
    <!doctype html>
    <html lang="en"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>T3 Code nightly for Android</title>
    <body><h1>T3 Code nightly for Android</h1>
    <p>Official Android build attached to server nightly ${package.version}.</p>
    <p><a href="/nightly.apk">Download Android APK</a></p>
    <p>Build: ${package.mobileApkName}</p>
    <p>Enable Tailscale, download, then confirm installation on your phone.
    Android may ask you to allow installations from your browser.</p>
    <p>Connect to <a href="https://t3code.${homelab.internalDomain}">T3 Code</a>
    using a fresh pairing code.</p>
    <p>This link follows the server's daily nightly updates. Installing a new APK
    requires confirmation. Compatible in-app updates are provided by upstream.</p>
    </body></html>
  '';
  mobileManifest = pkgs.writeText "t3code-nightly-release.json" (
    builtins.toJSON {
      serverVersion = package.version;
      apkName = package.mobileApkName;
      apkHash = package.mobileApkHash;
      apkUrl = "/nightly.apk";
    }
  );
  mobileDownloads = pkgs.runCommand "t3code-nightly-mobile-${package.version}" { } ''
    mkdir -p "$out"
    ln -s ${mobileIndex} "$out/index.html"
    ln -s ${mobileManifest} "$out/release.json"
    ln -s ${package.mobileApk} "$out/nightly.apk"
    ln -s nightly.apk "$out/bootstrap.apk"
  '';
in
{
  options.homelab.t3code = {
    enable = lib.mkEnableOption "T3 Code private coding-agent web UI";
    port = lib.mkOption {
      type = lib.types.port;
      default = 3773;
      description = "Loopback port used by the T3 Code server.";
    };
  };
  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ package androidSdk ];
    nixpkgs.config.android_sdk.accept_license = true;
    # Upstream downloads version-matched Chrome and device helper binaries.
    programs.nix-ld.enable = true;
    programs.nix-ld.libraries = with pkgs; [
      nss nspr glib atk at-spi2-atk at-spi2-core dbus
      libX11 libxcb libXcomposite libXdamage libXext libXfixes
      libXrandr libxkbcommon mesa alsa-lib expat cups pango cairo
      libdrm libGL zlib fontconfig freetype
    ];
    systemd.tmpfiles.rules = [ "d ${stateDir} 0700 rishabh users - -" ];
    systemd.services.t3code = {
      description = "Official T3 Code nightly server";
      # Keep active sessions alive across deployments, as with Codex.
      restartIfChanged = false;
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      path = with pkgs; [
        bash
        ffmpeg
        poppler-utils
        nodejs
        jdk
        android-tools
        procps
        unzip
        curl
        coreutils
        fd
        findutils
        gh
        git
        gnugrep
        gnused
        jq
        just
        nix
        openssh
        ripgrep
      ];
      environment = {
        ANDROID_HOME = "${androidSdk}/libexec/android-sdk";
        JAVA_HOME = "${pkgs.jdk}";
        CODEX_HOME = homelab.paths.codexHome;
        HOME = homelab.paths.userHome;
        SHELL = "${pkgs.bash}/bin/bash";
        T3CODE_HOME = stateDir;
      };
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        WorkingDirectory = stateDir;
        ExecStart = "${package}/bin/t3 serve --host 127.0.0.1 --port ${toString cfg.port} --base-dir ${stateDir} --no-browser";
        Restart = "on-failure";
        RestartSec = "5s";
        UMask = "0077";
      };
    };
    systemd.services.t3code-auto-update = {
      description = "Update T3 Code to the latest official nightly";
      wants = [ "network-online.target" ];
      after = [
        "network-online.target"
        "pi-auto-update.service"
      ];
      path = with pkgs; [
        bash
        coreutils
        curl
        gawk
        gnugrep
        git
        gh
        jq
        just
        nix
        nixos-rebuild
        perl
        sudo
        systemd
        util-linux
      ];
      environment = {
        HOMELAB_DEV_ROOT = homelab.paths.devRoot;
        HOMELAB_DEPLOY_ROOT = homelab.paths.opsRoot;
        HOST = config.networking.hostName;
      };
      serviceConfig = {
        Type = "oneshot";
        WorkingDirectory = homelab.paths.devRoot;
        ExecStart = "${homelab.paths.opsRoot}/components/t3code/bin/auto-update";
      };
    };
    systemd.timers.t3code-auto-update = {
      description = "Daily official T3 Code nightly update";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "*-*-* 06:00:00";
        Persistent = true;
        RandomizedDelaySec = "10m";
        Unit = "t3code-auto-update.service";
      };
    };
    homelab.routes.t3code = {
      enable = true;
      host = "t3code";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private official T3 Code nightly UI";
    };
    homelab.routes.t3code-updates = {
      enable = true;
      host = "updates";
      visibility = "internal";
      description = "Official Android APK from the deployed T3 Code nightly";
      caddyConfig = ''
        @outsideTailnet not remote_ip 100.64.0.0/10 fd7a:115c:a1e0::/48
        respond @outsideTailnet "Tailnet access required." 403
        root * ${mobileDownloads}
        header Cache-Control "no-store"
        @apk path /nightly.apk /bootstrap.apk
        header @apk {
          Content-Type application/vnd.android.package-archive
          Content-Disposition "attachment; filename=t3code-nightly.apk"
        }
        file_server
      '';
    };
    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.t3code.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
    ];
  };
}
