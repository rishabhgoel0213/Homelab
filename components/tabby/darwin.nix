{
  inputs,
  pkgs,
  ...
}:

let
  tabbyPlugins = pkgs.callPackage ./plugins/package.nix { };
  tabbyTerminal = pkgs.callPackage ./package.nix {
    src = inputs.tabby-terminal;
    inherit tabbyPlugins;
  };
in
{
  environment.systemPackages = [ tabbyTerminal ];
}
