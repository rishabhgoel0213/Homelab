{
  description = "Declarative ops repo for therealrishabh.com homelab services";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";

    nix-darwin = {
      url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    fenix = {
      url = "github:nix-community/fenix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    tabby-terminal = {
      url = "git+file:///home/rishabh/Projects/tabby?ref=master";
      flake = false;
    };

    zen-browser = {
      url = "git+file:///home/rishabh/Projects/zen-browser?ref=dev";
      flake = false;
    };

    mautrix-meta-homelab = {
      url = "git+file:///home/rishabh/Projects/mautrix-meta?ref=main";
      flake = false;
    };

    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      nix-darwin,
      sops-nix,
      ...
    }:
    let
      system = "x86_64-linux";
      darwinSystem = "aarch64-darwin";
      pkgs = nixpkgs.legacyPackages.${system};
      unstablePkgs = inputs.nixpkgs-unstable.legacyPackages.${system};
      unsupportedLinuxPkgs = import nixpkgs {
        inherit system;
        config.allowUnsupportedSystem = true;
      };
      darwinPkgs = import nixpkgs {
        system = darwinSystem;
        config = {
          allowUnfree = true;
          permittedInsecurePackages = [ "electron-38.8.4" ];
        };
      };
      fenixPackages = inputs.fenix.packages.${system};
      rustManifestHash = "sha256-gh/xTkxKHL4eiRXzWv8KP7vfjSk61Iq48x47BEDFgfk=";
      hostRustToolchain = fenixPackages.fromToolchainName {
        name = "1.95.0";
        sha256 = rustManifestHash;
      };
      darwinRustTarget = fenixPackages.targets."aarch64-apple-darwin".fromToolchainName {
        name = "1.95.0";
        sha256 = rustManifestHash;
      };
      darwinRustToolchain = fenixPackages.combine [
        hostRustToolchain.cargo
        hostRustToolchain.rustc
        darwinRustTarget.rust-std
      ];
      macbookCodex = pkgs.callPackage ./components/codex/cross-package.nix {
        macosSdk = unsupportedLinuxPkgs.apple-sdk_15.src;
        rustToolchain = darwinRustToolchain;
      };
      macbookTabbyPlugins = pkgs.callPackage ./components/tabby/plugins/package.nix { };
      macbookTabby = pkgs.callPackage ./components/tabby/prebuilt-archive.nix { };
      macbookZen = pkgs.callPackage ./components/zen/prebuilt-archive.nix { };
      zenEngineSource = pkgs.callPackage ./components/zen/source-engine.nix {
        src = inputs.zen-browser;
      };
      macbookZenSource = pkgs.callPackage ./components/zen/cross-package.nix {
        engineSource = zenEngineSource;
        rustCbindgen = unstablePkgs.rust-cbindgen;
        rustToolchain = darwinRustToolchain;
      };
      macbookArtifactPathStrings = import ./components/darwin-deploy/artifacts.nix;
      macbookArtifacts = builtins.mapAttrs (_: path: builtins.storePath path) macbookArtifactPathStrings;
      darwinTabbyPrebuilt = darwinPkgs.callPackage ./components/tabby/prebuilt-package.nix {
        archive = macbookArtifacts.tabby;
      };
      darwinZenPrebuilt = darwinPkgs.callPackage ./components/zen/prebuilt-package.nix {
        archive = macbookArtifacts.zen;
      };
      macbookPackages = {
        tabby = darwinTabbyPrebuilt;
        zen = darwinZenPrebuilt;
      };
      darwinTabbySource = darwinPkgs.callPackage ./components/tabby/package.nix {
        src = inputs.tabby-terminal;
        tabbyPlugins = macbookTabbyPlugins;
      };
      darwinZenSource = darwinPkgs.callPackage ./components/zen/package.nix {
        archive = macbookArtifacts.zenSource;
      };
      macbookPackagesWithZenSource = macbookPackages // {
        zenSource = darwinZenSource;
      };
      pythonWithWebsocket = pkgs.python3.withPackages (ps: [ ps.websocket-client ]);
      pythonForBlog = pkgs.python3.withPackages (ps: [
        ps.aiohttp
        ps.pyyaml
      ]);
      cmsc216CheckPackages = pkgs.callPackage ./components/cmsc216/package.nix {
        inherit pkgs;
        directoryId = "r1shabhg";
        localRoot = "/Users/rishabhgoel/Projects/fall-2026/cmsc216";
        remoteRoot = "/home/r1shabhg/216-sync";
        dataRoot = "/Users/rishabhgoel/Library/Application Support/CMSC216/VSCodium";
      };
    in
    {
      checks.${system} = {
        cmsc216 =
          pkgs.runCommand "cmsc216-check"
            {
              nativeBuildInputs = [
                pkgs.jq
                pkgs.openssh
                pkgs.shellcheck
              ];
            }
            ''
              bash -n ${./components/cmsc216/bin/cmsc216}
              shellcheck ${./components/cmsc216/bin/cmsc216}
              bash -n ${./components/cmsc216/tests/auth.bash}
              bash -n ${./components/cmsc216/tests/fake-ssh}
              shellcheck ${./components/cmsc216/tests/auth.bash}
              shellcheck ${./components/cmsc216/tests/fake-ssh}
              cp ${./components/cmsc216/tests/fake-ssh} "$TMPDIR/fake-ssh"
              chmod +x "$TMPDIR/fake-ssh"
              patchShebangs "$TMPDIR/fake-ssh"
              bash ${./components/cmsc216/tests/auth.bash} \
                ${./components/cmsc216/bin/cmsc216} "$TMPDIR/fake-ssh"
              awk '
                /set \+u/ { nounset_disabled = NR }
                /^[[:space:]]*set --[[:space:]]*$/ { arguments_cleared = NR }
                /source ~profk\/bin\/cmsc216-setup/ { setup_sourced = NR }
                END {
                  exit !(nounset_disabled < setup_sourced && arguments_cleared < setup_sourced)
                }
              ' ${./components/cmsc216/bin/cmsc216}
              grep -Fq 'PubkeyAuthentication no' ${./components/cmsc216/darwin.nix}
              grep -Fq 'PreferredAuthentications keyboard-interactive,password' ${./components/cmsc216/darwin.nix}
              grep -Fq 'ControlPersist' ${./components/cmsc216/darwin.nix}
              grep -Fq 'sync_root="$CMSC216_LOCAL_ROOT"' ${./components/cmsc216/bin/cmsc216}
              ! grep -Fq 'GlobalProtect' ${./components/cmsc216/bin/cmsc216}
              ! grep -Fq 'sftp-neo' ${./components/cmsc216/bin/cmsc216}
              jq -e . ${cmsc216CheckPackages.settings} >/dev/null
              jq -e . ${cmsc216CheckPackages.workspace} >/dev/null

              jq -e '.extensions.recommendations == ["llvm-vs-code-extensions.vscode-clangd"]' \
                ${cmsc216CheckPackages.workspace} >/dev/null
              jq -e '.folders == [{"name":"cmsc216","path":"/Users/rishabhgoel/Projects/fall-2026/cmsc216"}]' \
                ${cmsc216CheckPackages.workspace} >/dev/null
              jq -e '.extensions.unwantedRecommendations | index("PhilipDaoud.sftp-neo") != null' \
                ${cmsc216CheckPackages.workspace} >/dev/null
              jq -e '[.tasks.tasks[].args[0]] | contains(["auth", "auth-status", "auth-clear", "sync", "test", "shell", "run", "format", "exam-check"])' \
                ${cmsc216CheckPackages.workspace} >/dev/null

              fingerprint="$(ssh-keygen -lf ${./components/cmsc216/config/zaratan-known-hosts} -E sha256 | awk '{print $2}')"
              test "$fingerprint" = "SHA256:Ot4bTjdmv3t8Lwn2uETVlAFPzhFoQafQ7tt+oHAN69w"
              touch "$out"
            '';

        bonsai-ternary =
          pkgs.runCommand "bonsai-ternary-check"
            {
              nativeBuildInputs = [
                pkgs.nodejs_24
                pkgs.shellcheck
              ];
            }
            ''
              shellcheck ${./components/local-models/bonsai/download-model.sh}
              node --check ${./components/local-models/bonsai/proxy.mjs}
              touch "$out"
            '';

        nemotron-lightning =
          pkgs.runCommand "nemotron-lightning-check"
            {
              nativeBuildInputs = [
                pkgs.nodejs_24
                pkgs.shellcheck
              ];
            }
            ''
              shellcheck ${./components/local-models/nemotron-lightning/download-model.sh}
              node --check ${./components/local-models/nemotron-lightning/proxy.mjs}
              touch "$out"
            '';

        mach1-additive =
          pkgs.runCommand "mach1-additive-check"
            {
              nativeBuildInputs = [ pkgs.nodejs_24 ];
            }
            ''
              node --check ${./components/local-models/mach1/app/server.mjs}
              node --check ${./components/local-models/mach1/app/web/runtime.js}
              node --check ${./components/local-models/mach1/app/web/reasoning.mjs}
              node --check ${./components/local-models/mach1/app/web/tool-calls.mjs}
              node --check ${./components/local-models/mach1/download-model.mjs}
              node ${./components/local-models/mach1}/tests/test-tool-calls.mjs
              node ${./components/local-models/mach1}/tests/test-reasoning.mjs
              touch "$out"
            '';

        projectctl =
          pkgs.runCommand "projectctl-check"
            {
              nativeBuildInputs = [
                pkgs.python3
                pkgs.ruff
              ];
            }
            ''
              ruff check ${./components/projects/bin/projectctl.py} ${./components/projects/tests/test-projectctl.py}
              python3 -m py_compile ${./components/projects/bin/projectctl.py} ${./components/projects/tests/test-projectctl.py}
              PROJECTCTL_SCRIPT=${./components/projects/bin/projectctl.py} \
                python3 ${./components/projects/tests/test-projectctl.py}
              touch "$out"
            '';

        blog-admin =
          pkgs.runCommand "blog-admin-check"
            {
              nativeBuildInputs = [
                pkgs.nodejs_24
                pythonForBlog
                pkgs.ruff
              ];
            }
            ''
              node --check ${./components/blog/assets/app.js}
              ruff check ${./components/blog/bin/blog-admin.py} ${./components/blog/tests/test-blog-admin.py}
              python3 -m py_compile ${./components/blog/bin/blog-admin.py} ${./components/blog/tests/test-blog-admin.py}
              BLOG_ADMIN_SCRIPT=${./components/blog/bin/blog-admin.py} \
                BLOG_ADMIN_ASSETS=${./components/blog/assets} \
                python3 ${./components/blog/tests/test-blog-admin.py}
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
              ruff check ${./components/canvas-bridge/bin/canvas-bridge.py} ${./components/canvas-bridge/tests/test-canvas-bridge.py}
              python3 -m py_compile ${./components/canvas-bridge/bin/canvas-bridge.py}
              CANVAS_BRIDGE_SCRIPT=${./components/canvas-bridge/bin/canvas-bridge.py} \
                python3 ${./components/canvas-bridge/tests/test-canvas-bridge.py}
              touch "$out"
            '';

        singlemail =
          pkgs.runCommand "singlemail-check"
            {
              nativeBuildInputs = [
                pkgs.nodejs_24
                pkgs.python3
                pkgs.ruff
                pkgs.shellcheck
                pkgs.typescript
                pkgs.wrangler
              ];
            }
            ''
              export HOME="$TMPDIR/home"
              export XDG_CACHE_HOME="$TMPDIR/cache"
              export XDG_CONFIG_HOME="$TMPDIR/config"
              mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"

              ruff check ${./components/singlemail/bin/singlemail.py} ${./components/singlemail/tests/test-singlemail.py}
              python3 -m py_compile ${./components/singlemail/bin/singlemail.py}
              SINGLEMAIL_SCRIPT=${./components/singlemail/bin/singlemail.py} \
                python3 ${./components/singlemail/tests/test-singlemail.py}
              shellcheck ${./components/singlemail/bin/cloudflare-deploy} \
                ${./components/singlemail/bin/store-token}
              cp -R ${./components/singlemail/worker} "$TMPDIR/worker"
              chmod -R u+w "$TMPDIR/worker"
              cd "$TMPDIR/worker"
              tsc --noEmit
              wrangler deploy --dry-run --outdir "$TMPDIR/worker-build"
              touch "$out"
            '';

        t3code-updates =
          pkgs.runCommand "t3code-updates-check"
            {
              nativeBuildInputs = [ pkgs.python3 ];
            }
            ''
              python3 -m py_compile ${./components/t3code/bin/updates-server.py}
              T3CODE_UPDATES_SERVER_SCRIPT=${./components/t3code/bin/updates-server.py} \
                python3 ${./components/t3code/tests/test-updates-server.py}
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
              ruff check ${./components/remote-phone/bin/remote-phone-mic.py} ${./components/remote-phone/tests/test-remote-phone-mic.py}
              python3 -m py_compile ${./components/remote-phone/bin/remote-phone-mic.py}
              REMOTE_PHONE_SCRIPT=${./components/remote-phone/bin/remote-phone-mic.py} \
                python3 ${./components/remote-phone/tests/test-remote-phone-mic.py}
              touch "$out"
            '';
      };

      packages.${system} = {
        macbook-codex = macbookCodex;
        macbook-tabby-plugins = macbookTabbyPlugins;
        macbook-tabby = macbookTabby;
        macbook-zen = macbookZen;
        macbook-zen-engine-source = zenEngineSource;
        macbook-zen-source = macbookZenSource;
      };

      packages.${darwinSystem} = {
        cmsc216 = self.darwinConfigurations.macbook.config.homelab.coursework.cmsc216.package;
        cmsc216-cli = self.darwinConfigurations.macbook.config.homelab.coursework.cmsc216.cliPackage;
        codex = macbookCodex;
        tabby-plugins = macbookTabbyPlugins;
        tabby = darwinTabbyPrebuilt;
        tabby-source = darwinTabbySource;
        zen = darwinZenPrebuilt;
        zen-source = darwinZenSource;
        macbook-system = self.darwinConfigurations.macbook.system;
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

      darwinConfigurations.macbook = nix-darwin.lib.darwinSystem {
        system = "aarch64-darwin";
        specialArgs = {
          inherit
            inputs
            macbookArtifacts
            self
            ;
          macbookPackages = macbookPackagesWithZenSource;
        };
        modules = [
          ./hosts/macbook
        ];
      };
    };
}
