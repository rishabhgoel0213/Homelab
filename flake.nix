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
      vscodiumProjectsExtension =
        pkgs.callPackage ./components/vscodium/projects-extension/package.nix
          { };
      vscodiumOpenRemoteSsh = pkgs.callPackage ./components/vscodium/open-remote-ssh/package.nix { };
      vscodiumGeneralJupyterTempDir = "/Users/rishabhgoel/Library/Application Support/Homelab VSCodium/general/extension-data/ms-toolsai.jupyter/temp";
      vscodiumLocalJupyterTempDir = "/Users/rishabhgoel/Library/Application Support/Homelab VSCodium/scratch/extension-data/ms-toolsai.jupyter/temp";
      vscodiumGeneralExtensionSets = import ./components/vscodium/extensions.nix {
        inherit pkgs;
        projectsExtension = vscodiumProjectsExtension;
        jupyterTempDir = vscodiumGeneralJupyterTempDir;
      };
      vscodiumLocalExtensionSets = import ./components/vscodium/extensions.nix {
        inherit pkgs;
        projectsExtension = vscodiumProjectsExtension;
        jupyterTempDir = vscodiumLocalJupyterTempDir;
      };
      cmsc216CheckPackages = pkgs.callPackage ./components/cmsc216/package.nix {
        inherit pkgs;
        directoryId = "r1shabhg";
        localRoot = "/Users/rishabhgoel/Projects/fall-2026/cmsc216";
        remoteRoot = "/home/r1shabhg/216-sync";
        dataRoot = "/Users/rishabhgoel/Library/Application Support/CMSC216/VSCodium";
        codiumBin = "${cmsc216EditorCheckPackages.codium}/bin/codium-cmsc216";
      };
      cmsc216EditorCheckPackages = pkgs.callPackage ./components/vscodium/package.nix {
        presetName = "cmsc216";
        displayName = "VSCodium 216";
        bundleIdentifier = "com.therealrishabh.cmsc216";
        dataRoot = "/Users/rishabhgoel/Library/Application Support/CMSC216/VSCodium";
        icon = ./components/vscodium/icons/VSCodium-CMSC216.icns;
        extensions = [ pkgs.vscode-extensions.llvm-vs-code-extensions.vscode-clangd ];
        settings = cmsc216CheckPackages.settings;
        workspace = cmsc216CheckPackages.workspace;
        appVersion = "2026.3";
      };
      vscodiumGeneralCheckPackages = pkgs.callPackage ./components/vscodium/package.nix {
        presetName = "general";
        displayName = "VSCodium Remote";
        bundleIdentifier = "com.therealrishabh.vscodium";
        dataRoot = "/Users/rishabhgoel/Library/Application Support/Homelab VSCodium/general";
        icon = ./components/vscodium/icons/VSCodium-Remote.icns;
        extensions = vscodiumGeneralExtensionSets.full ++ vscodiumGeneralExtensionSets.remoteClient;
        settings = {
          "remote.SSH.remotePlatform".nixos-pc = "linux";
          "remote.SSH.serverInstallPath".nixos-pc = "/home/rishabh/.vscodium-server";
          "telemetry.telemetryLevel" = "off";
          "update.mode" = "none";
        };
        remoteHost = "nixos-pc";
        remotePath = "/home/rishabh/Projects";
        localPathPrefix = "/Users/rishabhgoel/Projects";
        appVersion = "2026.4";
      };
      vscodiumLocalCheckPackages = pkgs.callPackage ./components/vscodium/package.nix {
        presetName = "local";
        displayName = "VSCodium Local";
        bundleIdentifier = "com.therealrishabh.vscodium.local";
        dataRoot = "/Users/rishabhgoel/Library/Application Support/Homelab VSCodium/scratch";
        icon = ./components/vscodium/icons/VSCodium-Local.icns;
        extensions = vscodiumLocalExtensionSets.full;
        mutableExtensions = true;
        appVersion = "2026.3";
      };
      vscodiumDispatcherCheckPackage = pkgs.callPackage ./components/vscodium/dispatcher.nix {
        presets.general = {
          displayName = "VSCodium Remote";
          cli = vscodiumGeneralCheckPackages.cli;
        };
      };
      vscodiumRemoteActivationScript = pkgs.writeShellScript "vscodium-remote-activation-check" (
        self.nixosConfigurations.nixos-pc.config.system.activationScripts.vscodiumRemoteExtensions.text
      );
      zenDevtoolsMcp = pkgs.callPackage ./components/zen/devtools-mcp/package.nix { };
    in
    {
      checks.${system} = {
        zen-devtools-mcp =
          pkgs.runCommand "zen-devtools-mcp-check"
            {
              nativeBuildInputs = [ zenDevtoolsMcp ];
            }
            ''
              test "$(firefox-devtools-mcp --version)" = "0.10.2"
              firefox-devtools-mcp --help | grep -Fq -- "--toolPreset"
              touch "$out"
            '';

        zen-managed-sidebar =
          pkgs.runCommand "zen-managed-sidebar-check"
            {
              nativeBuildInputs = [
                pkgs.nodejs_24
                pkgs.shellcheck
                pkgs.python3
              ];
            }
            ''
              node --check ${inputs.zen-browser}/src/zen/sync/ZenManagedSidebarCompiler.sys.mjs
              node --check ${inputs.zen-browser}/src/zen/sync/ZenManagedSidebar.sys.mjs
              node --check ${inputs.zen-browser}/src/zen/space-routing/ZenSpaceRoutingManager.sys.mjs
              node --check ${inputs.zen-browser}/src/zen/sync/ZenSpacesSyncApplier.sys.mjs
              node --check ${./components/zen/tests/chrome-smoke.js}
              shellcheck ${./hosts/macbook/deploy-zen-layout}
              bash -n ${./hosts/macbook/deploy-zen-layout}
              LAYOUT_DEPLOY_SCRIPT=${./hosts/macbook/deploy-zen-layout} \
                python3 ${./components/zen/tests/test-layout-deploy.py}
              ZEN_SPACES_SYNC_APPLIER=${inputs.zen-browser}/src/zen/sync/ZenSpacesSyncApplier.sys.mjs \
                node --experimental-vm-modules ${./components/zen/tests/space-deletion.mjs}
              ZEN_MANAGED_SIDEBAR_COMPILER=${inputs.zen-browser}/src/zen/sync/ZenManagedSidebarCompiler.sys.mjs \
                ZEN_MANAGED_SIDEBAR_MANIFEST=${
                  pkgs.writeText "macbook-managed-sidebar.json"
                    self.darwinConfigurations.macbook.config.environment.etc."zen/managed-sidebar.json".text
                } \
                node ${./components/zen/tests/managed-sidebar.mjs}
              touch "$out"
            '';

        vscodium =
          pkgs.runCommand "vscodium-check"
            {
              nativeBuildInputs = [
                pkgs.jq
                pkgs.nodejs_24
                pkgs.shellcheck
                pkgs.file
              ];
            }
            ''
              node --check ${./components/vscodium/projects-extension/extension.js}
              jq -e '.publisher == "therealrishabh" and .name == "projects"' \
                ${./components/vscodium/projects-extension/package.json} >/dev/null
              jq -e '.extensionKind == ["workspace"]' \
                ${./components/vscodium/projects-extension/package.json} >/dev/null
              jq -e '."telemetry.telemetryLevel" == "off"' \
                ${vscodiumGeneralCheckPackages.settingsFile} >/dev/null
              jq -e '."remote.SSH.remotePlatform"["nixos-pc"] == "linux"' \
                ${vscodiumGeneralCheckPackages.settingsFile} >/dev/null
              jq -e '."remote.SSH.serverInstallPath"["nixos-pc"] == "/home/rishabh/.vscodium-server"' \
                ${vscodiumGeneralCheckPackages.settingsFile} >/dev/null
              jq -e 'map(.identifier.id) | index("therealrishabh.projects") != null' \
                ${vscodiumGeneralCheckPackages.managedExtensionDir}/share/vscode/extensions/extensions.json >/dev/null
              jq -e 'map(.identifier.id) | index("jeanp413.open-remote-ssh") != null' \
                ${vscodiumGeneralCheckPackages.managedExtensionDir}/share/vscode/extensions/extensions.json >/dev/null
              jq -e 'map(.identifier.id) | index("ms-vscode-remote.remote-ssh") == null' \
                ${vscodiumGeneralCheckPackages.managedExtensionDir}/share/vscode/extensions/extensions.json >/dev/null
              jq -e 'map(.identifier.id) | index("ms-toolsai.jupyter") != null' \
                ${vscodiumLocalCheckPackages.managedExtensionDir}/share/vscode/extensions/extensions.json >/dev/null
              jq -e 'map(.identifier.id) | index("therealrishabh.projects") != null' \
                ${vscodiumLocalCheckPackages.managedExtensionDir}/share/vscode/extensions/extensions.json >/dev/null
              jq -e '.version == "0.3.1" and (.activationEvents | index("onResolveRemoteAuthority:ssh-remote") != null)' \
                ${vscodiumOpenRemoteSsh}/share/vscode/extensions/jeanp413.open-remote-ssh/package.json >/dev/null
              test "$(readlink ${vscodiumGeneralExtensionSets.jupyter}/share/vscode/extensions/ms-toolsai.jupyter/temp)" = \
                ${pkgs.lib.escapeShellArg vscodiumGeneralJupyterTempDir}
              test "$(readlink ${vscodiumLocalExtensionSets.jupyter}/share/vscode/extensions/ms-toolsai.jupyter/temp)" = \
                ${pkgs.lib.escapeShellArg vscodiumLocalJupyterTempDir}
              shellcheck ${vscodiumGeneralCheckPackages.codium}/bin/codium-general
              shellcheck ${vscodiumGeneralCheckPackages.cli}/bin/vscodium-open-general
              grep -Fq -- '--extensions-dir' ${vscodiumGeneralCheckPackages.codium}/bin/codium-general
              grep -Fq -- '--user-data-dir' ${vscodiumGeneralCheckPackages.codium}/bin/codium-general
              grep -Fq -- '--remote' ${vscodiumGeneralCheckPackages.cli}/bin/vscodium-open-general
              grep -Fq -- 'ssh-remote+nixos-pc' ${vscodiumGeneralCheckPackages.cli}/bin/vscodium-open-general
              grep -Fq -- '/home/rishabh/Projects' ${vscodiumGeneralCheckPackages.cli}/bin/vscodium-open-general
              grep -Fq -- '--extensions-dir' ${vscodiumLocalCheckPackages.codium}/bin/codium-local
              grep -Fq -- ${pkgs.lib.escapeShellArg "/Users/rishabhgoel/Library/Application Support/Homelab VSCodium/scratch/extensions"} \
                ${vscodiumLocalCheckPackages.codium}/bin/codium-local
              grep -Fq 'vscode.env.remoteName' ${./components/vscodium/projects-extension/extension.js}
              for icon in \
                ${./components/vscodium/icons/VSCodium-Remote.icns} \
                ${./components/vscodium/icons/VSCodium-Local.icns} \
                ${./components/vscodium/icons/VSCodium-CMSC216.icns}; do
                file "$icon" | grep -Fq 'Mac OS X icon'
              done
              cmp ${./components/vscodium/icons/VSCodium-Remote.icns} \
                ${vscodiumGeneralCheckPackages.iconFile}
              cmp ${./components/vscodium/icons/VSCodium-Local.icns} \
                ${vscodiumLocalCheckPackages.iconFile}
              cmp ${./components/vscodium/icons/VSCodium-CMSC216.icns} \
                ${cmsc216EditorCheckPackages.iconFile}
              grep -Fq 'cp ''${iconFile}' ${./components/vscodium/package.nix}
              bash -n ${vscodiumRemoteActivationScript}
              shellcheck ${vscodiumRemoteActivationScript}
              grep -Fq '/home/rishabh/.vscodium-server/data/extension-data/ms-toolsai.jupyter/temp' \
                ${vscodiumRemoteActivationScript}
              grep -Fq 'install_settings "$data_root/User/settings.json"' ${./components/vscodium/darwin.nix}
              grep -Fq 'install_mutable_extensions' ${./components/vscodium/darwin.nix}
              ! grep -Fq 'manage_link "$data_root/User/settings.json"' ${./components/vscodium/darwin.nix}
              ${vscodiumDispatcherCheckPackage}/bin/vscodium-env list | grep -Fq 'general'
              ${vscodiumDispatcherCheckPackage}/bin/vscodium-env list | grep -Fq 'VSCodium Remote'
              if ${vscodiumDispatcherCheckPackage}/bin/vscodium-env open missing; then
                echo 'unknown VSCodium preset unexpectedly succeeded' >&2
                exit 1
              fi
              touch "$out"
            '';

        cmsc216 =
          pkgs.runCommand "cmsc216-check"
            {
              nativeBuildInputs = [
                pkgs.jq
                pkgs.openssh
                pkgs.shellcheck
                pkgs.python3
              ];
            }
            ''
              bash -n ${./components/cmsc216/bin/cmsc216}
              shellcheck ${./components/cmsc216/bin/cmsc216}
              PYTHONDONTWRITEBYTECODE=1 python3 ${./components/cmsc216}/tests/download-lab.py
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
              jq -e . ${cmsc216EditorCheckPackages.settingsFile} >/dev/null
              jq -e . ${cmsc216CheckPackages.workspace} >/dev/null
              jq -e 'map(.identifier.id) == ["llvm-vs-code-extensions.vscode-clangd"]' \
                ${cmsc216EditorCheckPackages.managedExtensionDir}/share/vscode/extensions/extensions.json >/dev/null

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
        vscodium-general =
          self.darwinConfigurations.macbook.config.homelab.apps.vscodium.generated.general.package;
        vscodium-local =
          self.darwinConfigurations.macbook.config.homelab.apps.vscodium.generated.local.package;
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
