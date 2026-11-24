{ pkgs, ... }:

{
  environment.systemPackages = [
    pkgs.gogcli
  ];
}
