{
  description = "Declarative ops repo for therealrishabh.com homelab services";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      sops-nix,
      ...
    }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      pythonWithWebsocket = pkgs.python3.withPackages (ps: [ ps.websocket-client ]);
    in
    {
      checks.${system} = {
        canvas-bridge = pkgs.runCommand "canvas-bridge-check" {
          nativeBuildInputs = [
            pkgs.python3
            pkgs.ruff
          ];
        } ''
          ruff check ${./scripts/canvas-bridge.py} ${./tests/test-canvas-bridge.py}
          python3 -m py_compile ${./scripts/canvas-bridge.py}
          CANVAS_BRIDGE_SCRIPT=${./scripts/canvas-bridge.py} \
            python3 ${./tests/test-canvas-bridge.py}
          touch "$out"
        '';

        remote-phone-mic = pkgs.runCommand "remote-phone-mic-check" {
          nativeBuildInputs = [
            pkgs.ruff
            pythonWithWebsocket
          ];
        } ''
          ruff check ${./scripts/remote-phone-mic.py} ${./tests/test-remote-phone-mic.py}
          python3 -m py_compile ${./scripts/remote-phone-mic.py}
          REMOTE_PHONE_SCRIPT=${./scripts/remote-phone-mic.py} \
            python3 ${./tests/test-remote-phone-mic.py}
          touch "$out"
        '';
      };

      nixosConfigurations.nixos-pc = nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = {
          inherit inputs self;
        };
        modules = [
          sops-nix.nixosModules.sops
          ./hosts/nixos-pc
        ];
      };
    };
}
