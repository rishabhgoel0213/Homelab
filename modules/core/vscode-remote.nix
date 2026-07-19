{ ... }:

{
  # VS Code Remote-SSH downloads a generic Linux server whose bundled Node.js
  # expects the standard FHS dynamic loader. Let those version-matched binaries
  # run without maintaining or exposing a separate VS Code service.
  programs.nix-ld.enable = true;
}
