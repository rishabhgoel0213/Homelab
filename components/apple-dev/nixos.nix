{ pkgs, ... }:

let
  cacheDir = "/var/cache/apple-dev";

  appleDev = pkgs.writeShellApplication {
    name = "apple-dev";
    runtimeInputs = with pkgs; [
      coreutils
      openssh
      python3
      zstd
    ];
    text = ''
      export APPLE_DEV_CACHE_DIR="''${APPLE_DEV_CACHE_DIR:-${cacheDir}}"
      exec ${pkgs.python3}/bin/python3 ${./apple-dev.py} "$@"
    '';
  };
in
{
  # Stored under /var/cache (outside Backrest's /srv/state backup mounts)
  # because Apple Xcode/Simulator artifacts are large and re-fetchable.
  systemd.tmpfiles.rules = [
    "d ${cacheDir} 0700 rishabh users - -"
  ];

  environment.systemPackages = [
    appleDev
  ];
}
