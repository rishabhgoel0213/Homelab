{ config, pkgs, ... }:
let
  sdk = (pkgs.androidenv.composeAndroidPackages {
    platformVersions = [ "35" "36" "37.0" ];
    buildToolsVersions = [ "35.0.0" "36.0.0" "37.0.0" ];
    includeNDK = true;
    ndkVersions = [ "27.1.12297006" ];
    cmakeVersions = [ "3.22.1" "3.30.5" ];
  }).androidsdk.overrideAttrs (old: {
    postInstall = (old.postInstall or "") + ''
      # Android's API 37 archive is published under a fractional package name.
      ln -s android-37.0 "$out/libexec/android-sdk/platforms/android-37"
    '';
  });
  host = pkgs.writeText "mobile-device-host.json" (builtins.toJSON {
    kind = "ssh"; id = "mobile-mac"; label = "MacBook iOS"; target = "mobile-ios";
  });
in {
  systemd.services.t3code-mobile-host = {
    description = "Register managed MacBook iOS host in T3";
    wantedBy = [ "multi-user.target" ];
    before = [ "t3code.service" ];
    serviceConfig = {
      Type = "oneshot"; User = "rishabh"; RemainAfterExit = true; UMask = "0077";
      ExecStart = "${pkgs.python3}/bin/python3 ${./register-host.py} /srv/state/t3code/userdata/settings.json ${host}";
    };
  };
  environment.etc."mobile-dev/android-sdk".source = "${sdk}/libexec/android-sdk";
  systemd.services.hackathon-mobile-metro = {
    description = "Hackathon Mobile Expo development server (tailnet only)";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    path = [ pkgs.nodejs_24 pkgs.git pkgs.bash ];
    environment = {
      HOME = "/home/rishabh";
      EXPO_OFFLINE = "1";
      EXPO_NO_TELEMETRY = "1";
      REACT_NATIVE_PACKAGER_HOSTNAME = config.homelab.tailnetIp;
    };
    serviceConfig = {
      User = "rishabh";
      WorkingDirectory = "/home/rishabh/Projects/hackathon-mobile/src/mobile";
      ExecStart = "${pkgs.nodejs_24}/bin/node node_modules/expo/bin/cli start --dev-client --host lan --port 8081";
      Restart = "on-failure";
      RestartSec = 5;
      UMask = "0077";
      # Metro listens on all addresses; restrict the entire process to loopback
      # and tailnet peers, independent of the host firewall's other interfaces.
      IPAddressDeny = "any";
      IPAddressAllow = [ "localhost" "100.64.0.0/10" "fd7a:115c:a1e0::/48" ];
    };
  };
  homelab.routes.mobile = {
    enable = true;
    host = "mobile";
    visibility = "internal";
    upstream = "http://127.0.0.1:8081";
    description = "Hackathon Mobile Expo Metro and web preview";
  };
  programs.ssh.extraConfig = ''
    Host mobile-ios
      SetEnv T3_DEVICE_IOS_ONLY=1
    Host mobile-mac mobile-ios
      HostName 100.105.159.13
      User rishabhgoel
      BatchMode yes
      ServerAliveInterval 15
      ServerAliveCountMax 3
  '';
}
