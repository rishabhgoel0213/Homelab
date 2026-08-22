{
  inputs,
  pkgs,
  ...
}:

let
  zenBrowser = pkgs.callPackage ./package.nix {
    src = inputs.zen-browser;
  };
in
{
  environment.systemPackages = [ zenBrowser ];
}
