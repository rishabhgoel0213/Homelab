{ config, lib, pkgs, ... }:
let
  package = pkgs.callPackage ./package.nix { };
  python = pkgs.python3.withPackages (p: [ p.websocket-client ]);
in {
  environment.systemPackages = [ package ];
  environment.etc."brick-admin-root".source = "${package.gate}/libexec/brick-admin-root";
  # The directory is initially empty; enrollment installs the restriction last.
  security.sudo.extraConfig = lib.mkAfter ''
    rishabh ALL=(root) NOPASSWD: NOSETENV: NOLOG_INPUT: NOLOG_OUTPUT: /etc/brick-admin-root
    @includedir /var/lib/brick-admin/sudoers.d
  '';
  systemd.tmpfiles.rules = [
    "d /var/lib/brick-admin 0700 root root -"
    "d /var/lib/brick-admin/sudoers.d 0700 root root -"
  ];
  # A privileged listener prevents an ordinary user impersonating the relay
  # during a restart. Ordinary Workmode continues using its existing endpoint.
  systemd.services.brick-admin-state = {
    wantedBy = [ "multi-user.target" ];
    after = [ "tailscaled.service" "sops-nix.service" ];
    serviceConfig = {
      ExecStart = "${python}/bin/python ${../workmode/brick_bridge.py} --port 1022 --token-file %d/phone-token --state-file /var/lib/brick-admin-state/latch.json";
      LoadCredential = "phone-token:${config.sops.secrets.remote-phone-token.path}";
      DynamicUser = true;
      StateDirectory = "brick-admin-state";
      AmbientCapabilities = [ "CAP_NET_BIND_SERVICE" ];
      CapabilityBoundingSet = [ "CAP_NET_BIND_SERVICE" ];
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      PrivateTmp = true;
      Restart = "always";
      RestartSec = 3;
    };
  };
  security.polkit.extraConfig = lib.mkBefore ''
    polkit.addRule(function(action, subject) {
      if (subject.user !== "rishabh") return polkit.Result.NOT_HANDLED;
      try { polkit.spawn(["${pkgs.coreutils}/bin/test", "-e", "/etc/brick-admin.enrolled"]); }
      catch (error) { return polkit.Result.NOT_HANDLED; }
      try { polkit.spawn(["${package.gate}/libexec/brick-admin-root", "probe"]); }
      catch (error) { return polkit.Result.NO; }
      return polkit.Result.NOT_HANDLED;
    });
  '';
  systemd.sockets.docker.socketConfig = {
    SocketGroup = lib.mkForce "root";
    SocketMode = lib.mkForce "0600";
  };
  # Apply the persistent socket mode on its next start; enrollment chmods
  # the current socket without restarting Docker or existing containers.
  systemd.sockets.docker.unitConfig.X-RestartIfChanged = false;
  boot.kernel.sysctl."net.ipv4.ip_unprivileged_port_start" = 1024;
}
