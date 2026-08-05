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
      pythonWithAiohttp = pkgs.python3.withPackages (ps: [ ps.aiohttp ]);
    in
    {
      checks.${system} = {
        mach1-additive =
          pkgs.runCommand "mach1-additive-check"
            {
              nativeBuildInputs = [ pkgs.nodejs_24 ];
            }
            ''
              node --check ${./local-models/mach1/app/server.mjs}
              node --check ${./local-models/mach1/app/web/runtime.js}
              node --check ${./local-models/mach1/app/web/reasoning.mjs}
              node --check ${./local-models/mach1/app/web/tool-calls.mjs}
              node --check ${./local-models/mach1/download-model.mjs}
              node ${./local-models/mach1}/tests/test-tool-calls.mjs
              node ${./local-models/mach1}/tests/test-reasoning.mjs
              touch "$out"
            '';

        agent-tools =
          pkgs.runCommand "agent-tools-check"
            {
              nativeBuildInputs = [
                pythonWithAiohttp
                pkgs.ruff
              ];
            }
            ''
              ruff check ${./scripts/agent.py} ${./scripts/agent-site-gateway.py} \
                ${./tests/test-agent-tools.py} ${./tests/test-agent-site-gateway.py}
              python3 -m py_compile ${./scripts/agent.py} ${./scripts/agent-site-gateway.py} \
                ${./tests/test-agent-tools.py} ${./tests/test-agent-site-gateway.py}
              AGENT_TOOL_SCRIPT=${./scripts/agent.py} \
                python3 ${./tests/test-agent-tools.py}
              AGENT_SITE_GATEWAY_SCRIPT=${./scripts/agent-site-gateway.py} \
                python3 ${./tests/test-agent-site-gateway.py}
              touch "$out"
            '';

        canvas-bridge =
          pkgs.runCommand "canvas-bridge-check"
            {
              nativeBuildInputs = [
                pkgs.python3
                pkgs.ruff
              ];
            }
            ''
              ruff check ${./scripts/canvas-bridge.py} ${./tests/test-canvas-bridge.py}
              python3 -m py_compile ${./scripts/canvas-bridge.py}
              CANVAS_BRIDGE_SCRIPT=${./scripts/canvas-bridge.py} \
                python3 ${./tests/test-canvas-bridge.py}
              touch "$out"
            '';

        remote-phone-mic =
          pkgs.runCommand "remote-phone-mic-check"
            {
              nativeBuildInputs = [
                pkgs.ruff
                pythonWithWebsocket
              ];
            }
            ''
              ruff check ${./scripts/remote-phone-mic.py} ${./tests/test-remote-phone-mic.py}
              python3 -m py_compile ${./scripts/remote-phone-mic.py}
              REMOTE_PHONE_SCRIPT=${./scripts/remote-phone-mic.py} \
                python3 ${./tests/test-remote-phone-mic.py}
              touch "$out"
            '';
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [
          age
          bashInteractive
          coreutils
          curl
          deadnix
          direnv
          fd
          findutils
          gh
          git
          jq
          just
          nil
          nixfmt-rfc-style
          openssh
          ripgrep
          rsync
          sops
          ssh-to-age
          statix
          tmux
          wget
        ];

        shellHook = ''
          export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-/tmp/codex-nix-cache}"
          export NIX_CONFIG="''${NIX_CONFIG:-experimental-features = nix-command flakes}"
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
