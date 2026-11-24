{ pkgs, ... }:

let
  appleDev = pkgs.writeShellApplication {
    name = "apple-dev";
    runtimeInputs = with pkgs; [
      coreutils
      openssh
      python3
      zstd
    ];
    text = ''
      export PATH="$PATH:/usr/bin:/bin:/usr/sbin:/sbin:/run/current-system/sw/bin"
      exec ${pkgs.python3}/bin/python3 ${./apple-dev.py} "$@"
    '';
  };
in
{
  environment.systemPackages = [
    appleDev
  ];
}
