{
  description = "Declarative ops repo for therealrishabh.com homelab services";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
    vaultwarden-nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    nix-darwin = {
      url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    fenix = {
      url = "github:nix-community/fenix";
      inputs.nixpkgs.follows = "nixpkgs";
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
      unsupportedLinuxPkgs = import nixpkgs {
        inherit system;
        config.allowUnsupportedSystem = true;
      };
      darwinPkgs = import nixpkgs {
        system = darwinSystem;
        config = {
          allowUnfree = true;
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
      macbookCodex = pkgs.callPackage ./components/codex/cross-package.nix { };
      macbookZen = pkgs.callPackage ./components/zen/prebuilt-archive.nix { };
      macbookArtifactPathStrings = import ./components/darwin-deploy/artifacts.nix;
      macbookArtifacts = builtins.mapAttrs (_: path: builtins.storePath path) macbookArtifactPathStrings;
      darwinZenPrebuilt = darwinPkgs.callPackage ./components/zen/prebuilt-package.nix {
        archive = macbookArtifacts.zen;
      };
      macbookPackages = {
        zen = darwinZenPrebuilt;
      };
      pythonForProjectPages = pkgs.python3.withPackages (ps: [
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
    in
    {
      checks.${system} = {
        claude =
          pkgs.runCommand "claude-check"
            {
              nativeBuildInputs = [
                pkgs.python3
                pkgs.ruff
                pkgs.shellcheck
              ];
            }
            ''
              ruff check ${./components/claude}
              shellcheck ${./components/claude/bin/auto-update} ${./components/claude/bin/update} ${./components/claude/bin/publish-mac}
              python3 ${./components/claude}/tests.py
              touch "$out"
            '';

        antigravity =
          pkgs.runCommand "antigravity-check"
            {
              nativeBuildInputs = [
                pkgs.python3
                pkgs.ruff
                pkgs.shellcheck
              ];
            }
            ''
              ruff check ${./components/antigravity}
              shellcheck ${./components/antigravity/bin/auto-update} ${./components/antigravity/bin/update} ${./components/antigravity/bin/publish-mac}
              python3 ${./components/antigravity}/tests.py
              touch "$out"
            '';

        homelab-workflow =
          pkgs.runCommand "homelab-workflow-check"
            {
              nativeBuildInputs = with pkgs; [
                bash
                coreutils
                findutils
                gawk
                git
                gnused
                perl
                python3
                shellcheck
                util-linux
              ];
            }
            ''
              export PYTHONDONTWRITEBYTECODE=1
              shellcheck ${./tools/deploy} ${./tools/auto-update}
              HOMELAB_DEPLOY_SCRIPT=${./tools/deploy} \
                HOMELAB_AUTO_UPDATE_SCRIPT=${./tools/auto-update} \
                python3 ${./tools/tests/workflow.py}
              touch "$out"
            '';
        asmhelp = pkgs.callPackage ./components/asmhelp/package.nix { };
        micro = pkgs.callPackage ./components/micro/package.nix { };

        tasks =
          pkgs.runCommand "tasks-check"
            {
              nativeBuildInputs = [
                pkgs.python3
                pkgs.ruff
              ];
            }
            ''
              export PYTHONDONTWRITEBYTECODE=1
              export PYTHONTZPATH=${pkgs.tzdata}/share/zoneinfo
              ruff check ${./components/tasks/bin/tasks.py} ${./components/tasks/tests/test-tasks.py}
              TASKS_SCRIPT=${./components/tasks/bin/tasks.py} \
                TASKS_WEB_DIR=${./components/tasks/web} \
                python3 ${./components/tasks/tests/test-tasks.py}
              touch "$out"
            '';

        codex-update =
          pkgs.runCommand "codex-update-check"
            {
              nativeBuildInputs = with pkgs; [
                python3
                bash
                git
                jq
                perl
                shellcheck
              ];
            }
            ''
              export PYTHONDONTWRITEBYTECODE=1
              shellcheck ${./components/codex/bin/update} ${./components/codex/bin/auto-update} ${./components/codex/bin/publish-mac}
              python3 ${./components/codex}/tests/update.py
              python3 ${./components/codex}/tests/mac_client.py
              touch "$out"
            '';

        space-wallpaper =
          pkgs.runCommand "space-wallpaper-check"
            {
              nativeBuildInputs = [
                (pkgs.python3.withPackages (ps: [ ps.pillow ]))
                pkgs.ruff
              ];
            }
            ''
              export PYTHONDONTWRITEBYTECODE=1
              ruff check ${./components/space-wallpaper}/wallpaper.py ${./components/space-wallpaper}/test_wallpaper.py
              python3 ${./components/space-wallpaper}/test_wallpaper.py
              touch "$out"
            '';

        brick-admin = pkgs.runCommand "brick-admin-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
          export PYTHONDONTWRITEBYTECODE=1
          python3 ${./components/brick-admin}/test_policy.py
          python3 ${./components/brick-admin}/test_gate.py
          touch $out
        '';
        workmode = pkgs.runCommand "workmode-check" { nativeBuildInputs = [ (pkgs.python3.withPackages (p: [ p.websocket-client ])) ]; } ''
          export PYTHONDONTWRITEBYTECODE=1
          python3 ${./components/workmode}/test_brick.py
          python3 ${./components/workmode}/test_workmode.py
          python3 ${./components/workmode}/workmode.py --config ${./components/workmode/profiles.json} validate
          touch $out
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
              PROJECTS_EXTENSION_PATH=${./components/vscodium/projects-extension/extension.js} \
                node ${./components/vscodium/projects-extension/test.js}
              jq -e '.publisher == "therealrishabh" and .name == "projects"' \
                ${./components/vscodium/projects-extension/package.json} >/dev/null
              jq -e '.version == "1.1.0"' \
                ${vscodiumProjectsExtension}/share/vscode/extensions/therealrishabh.projects/package.json >/dev/null
              jq -e '.extensionKind == ["workspace"]' \
                ${./components/vscodium/projects-extension/package.json} >/dev/null
              jq -e '
                (.contributes.commands | length) == 20
                and ([.activationEvents[] | sub("^onCommand:"; "")] | sort)
                  == ([.contributes.commands[].command] | sort)
              ' ${./components/vscodium/projects-extension/package.json} >/dev/null
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
              grep -Fq 'vscode.Uri.file(project.root)' \
                ${./components/vscodium/projects-extension/extension.js}
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
              PYTHONDONTWRITEBYTECODE=1 python3 ${./components/cmsc216}/tests/remote-environment.py ${./components/cmsc216/bin/cmsc216}
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
              jq -e '[.tasks.tasks[].args[0]] | contains(["auth", "auth-status", "auth-clear", "sync", "pull", "test", "shell", "run", "format", "exam-check"])' \
                ${cmsc216CheckPackages.workspace} >/dev/null

              fingerprint="$(ssh-keygen -lf ${./components/cmsc216/config/zaratan-known-hosts} -E sha256 | awk '{print $2}')"
              test "$fingerprint" = "SHA256:Ot4bTjdmv3t8Lwn2uETVlAFPzhFoQafQ7tt+oHAN69w"
              touch "$out"
            '';

        qwen-image-2-1 =
          pkgs.runCommand "qwen-image-2.1-check"
            {
              nativeBuildInputs = [
                pkgs.python3
                pkgs.shellcheck
              ];
            }
            ''
              shellcheck ${./components/local-models/qwen-image-2.1/download-model.sh}
              python3 -m py_compile ${./components/local-models/qwen-image-2.1/qwen_image_edit.py}
              QWEN_IMAGE_EDIT_SCRIPT=${./components/local-models/qwen-image-2.1/qwen_image_edit.py} \
                python3 ${./components/local-models/qwen-image-2.1/tests/test_qwen_image_edit.py}
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

        project-pages = pkgs.runCommand "project-pages-check"
          { nativeBuildInputs = [ pythonForProjectPages pkgs.ruff ]; }
          ''
            ruff check ${./components/projects/bin/project-pages.py} ${./components/projects/tests/test-project-pages.py}
            PROJECT_PAGES_SCRIPT=${./components/projects/bin/project-pages.py} \
              python3 ${./components/projects/tests/test-project-pages.py}
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

        t3code-update =
          pkgs.runCommand "t3code-update-check"
            {
              nativeBuildInputs = [
                pkgs.shellcheck
                pkgs.python3
                pkgs.ruff
                pkgs.nodejs
                pkgs.bash
                pkgs.coreutils
                pkgs.jq
                pkgs.perl
              ];
            }
            ''
              export PYTHONDONTWRITEBYTECODE=1
              shellcheck ${./components/t3code/bin/update} ${./components/t3code/bin/auto-update} ${./components/t3code/bin/doctor} ${./components/t3code/bin/publish-mac}
              ruff check ${./components/t3code/mac-client.py} ${./components/t3code/tests/mac_client.py} ${./components/t3code/zen-cookie-sync.py} ${./components/t3code/browser-cookie-receive.py} ${./components/t3code/tests/browser_cookie_sync.py}
              node --check ${./components/t3code/browser-cookie-inject.mjs}
              T3CODE_UPDATE_SCRIPT=${./components/t3code/bin/update} \
                python3 ${./components/t3code/tests/update.py}
              T3CODE_MAC_CLIENT=${./components/t3code/mac-client.py} \
                python3 ${./components/t3code/tests/mac_client.py}
              T3CODE_ZEN_COOKIE_SYNC=${./components/t3code/zen-cookie-sync.py} \
              T3CODE_BROWSER_COOKIE_RECEIVE=${./components/t3code/browser-cookie-receive.py} \
                python3 ${./components/t3code/tests/browser_cookie_sync.py}
              touch "$out"
            '';

        zen-space-router =
          let
            pythonWithHttpx = pkgs.python3.withPackages (ps: [
              ps.httpx
              ps.h2
            ]);
            xpiPkg = pkgs.callPackage ./components/zen/space-router/package.nix { };
          in
          pkgs.runCommand "zen-space-router-check"
            {
              nativeBuildInputs = [
                pkgs.jq
                pkgs.nodejs_24
                pkgs.ruff
                pkgs.unzip
                pythonWithHttpx
              ];
            }
            ''
              ruff check ${./components/zen/space-router/server.py} ${./components/zen/space-router/tests/test_server.py}
              python3 -m py_compile ${./components/zen/space-router/server.py}
              ZEN_SPACE_ROUTER_SCRIPT=${./components/zen/space-router/server.py} \
                python3 ${./components/zen/space-router/tests/test_server.py}
              jq empty ${./components/zen/space-router/extension/manifest.json}
              jq empty ${./components/zen/space-router/extension/experiment/schema.json}
              node --check ${./components/zen/space-router/extension/experiment/api.js}
              node --check ${./components/zen/space-router/extension/background.js}
              node --check ${./components/zen/space-router/extension/popup.js}
              unzip -t "${xpiPkg}/share/zen-space-router/zen-space-router.xpi" >/dev/null
              touch "$out"
            '';

        google-workspace =
          pkgs.runCommand "google-workspace-check"
            {
              nativeBuildInputs = [
                pkgs.bash
                pkgs.coreutils
                pkgs.gawk
                pkgs.python3
                pkgs.ruff
                pkgs.shellcheck
              ];
            }
            ''
              export PYTHONDONTWRITEBYTECODE=1
              shellcheck ${./components/google-workspace/bin/gog-wrapper}
              ruff check ${./components/google-workspace/tests.py}
              GOG_WRAPPER_SCRIPT=${./components/google-workspace/bin/gog-wrapper} \
                python3 ${./components/google-workspace/tests.py}
              touch "$out"
            '';

        apple-dev =
          pkgs.runCommand "apple-dev-check"
            {
              nativeBuildInputs = [
                pkgs.python3
                pkgs.ruff
              ];
            }
            ''
              export PYTHONDONTWRITEBYTECODE=1
              ruff check ${./components/apple-dev/apple-dev.py} ${./components/apple-dev/tests.py}
              python3 -m py_compile ${./components/apple-dev/apple-dev.py}
              APPLE_DEV_SCRIPT=${./components/apple-dev/apple-dev.py} \
                python3 ${./components/apple-dev/tests.py}
              touch "$out"
            '';
      };

      packages.${system} = {
        codex = pkgs.callPackage ./components/codex/package.nix { };
        macbook-codex = macbookCodex;
        macbook-claude = pkgs.callPackage ./components/claude/package.nix { target = "darwin-arm64"; };
        macbook-antigravity = pkgs.callPackage ./components/antigravity/package.nix { target = "darwin-arm64"; };
        antigravity-acp = pkgs.callPackage ./components/antigravity/acp-package.nix { };
        t3code = pkgs.callPackage ./components/t3code/package.nix { };
        macbook-t3code = pkgs.callPackage ./components/t3code/package.nix { target = "darwin-arm64"; };
        macbook-zen = macbookZen;
        macbook-abstand = pkgs.callPackage ./components/workmode/archive.nix { };
      };

      packages.${darwinSystem} = {
        cmsc216 = self.darwinConfigurations.macbook.config.homelab.coursework.cmsc216.package;
        cmsc216-cli = self.darwinConfigurations.macbook.config.homelab.coursework.cmsc216.cliPackage;
        codex = macbookCodex;
        vscodium-general =
          self.darwinConfigurations.macbook.config.homelab.apps.vscodium.generated.general.package;
        vscodium-local =
          self.darwinConfigurations.macbook.config.homelab.apps.vscodium.generated.local.package;
        zen = darwinZenPrebuilt;
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
          inherit macbookPackages;
        };
        modules = [
          ./hosts/macbook
        ];
      };
    };
}
