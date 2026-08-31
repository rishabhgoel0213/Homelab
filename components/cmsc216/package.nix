{
  lib,
  pkgs,
  directoryId,
  localRoot,
  remoteRoot,
  identityFile,
  dataRoot,
  autoOpenGlobalProtect ? true,
  globalProtectApp ? "/Applications/GlobalProtect.app",
}:

let
  sftpNeo = pkgs.vscode-utils.buildVscodeMarketplaceExtension {
    mktplcRef = {
      name = "sftp-neo";
      publisher = "PhilipDaoud";
      version = "3.4.0";
      hash = "sha256-E15/nwSGLZj2C0UQFEHUhRnieZNmcN6+UToY+PlpxEA=";
    };
    meta = {
      description = "Modern SFTP extension used by the CMSC 216 coding environment";
      homepage = "https://marketplace.visualstudio.com/items?itemName=PhilipDaoud.sftp-neo";
      license = lib.licenses.mit;
    };
  };

  managedExtensions = [
    pkgs.vscode-extensions.llvm-vs-code-extensions.vscode-clangd
    sftpNeo
  ];

  extensionJsonFile = pkgs.writeTextFile {
    name = "cmsc216-vscode-extensions-json";
    destination = "/share/vscode/extensions/extensions.json";
    text = pkgs.vscode-utils.toExtensionJson managedExtensions;
  };

  managedExtensionDir = pkgs.buildEnv {
    name = "cmsc216-vscode-extensions";
    paths = managedExtensions ++ [ extensionJsonFile ];
  };

  # nixpkgs' generic vscode-with-extensions Darwin wrapper assumes that every
  # VS Code bundle uses Contents/MacOS/Electron. VSCodium uses
  # Contents/MacOS/VSCodium, so use the stable CLI entry point directly.
  managedVscodium = pkgs.writeShellScriptBin "codium" ''
    exec ${pkgs.vscodium}/bin/codium \
      --extensions-dir ${managedExtensionDir}/share/vscode/extensions \
      "$@"
  '';

  cli = pkgs.writeShellApplication {
    name = "cmsc216";
    runtimeInputs = [
      pkgs.clang-tools
      pkgs.coreutils
      pkgs.gnugrep
      pkgs.rsync
    ];
    text = ''
      export CMSC216_DIRECTORY_ID=${lib.escapeShellArg directoryId}
      export CMSC216_LOCAL_ROOT=${lib.escapeShellArg localRoot}
      export CMSC216_REMOTE_ROOT=${lib.escapeShellArg remoteRoot}
      export CMSC216_IDENTITY_FILE=${lib.escapeShellArg identityFile}
      export CMSC216_DATA_ROOT=${lib.escapeShellArg dataRoot}
      export CMSC216_CODIUM_BIN=${lib.escapeShellArg "${managedVscodium}/bin/codium"}
      export CMSC216_AUTO_OPEN_VPN=${if autoOpenGlobalProtect then "1" else "0"}
      export CMSC216_GLOBAL_PROTECT_APP=${lib.escapeShellArg globalProtectApp}

      ${builtins.readFile ./bin/cmsc216}
    '';
  };

  settings = pkgs.writeText "cmsc216-vscodium-settings.json" (
    builtins.toJSON {
      "chat.commandCenter.enabled" = false;
      "clangd.arguments" = [
        "--background-index"
        "--clang-tidy"
        "--completion-style=detailed"
      ];
      "clangd.path" = "${pkgs.clang-tools}/bin/clangd";
      "editor.formatOnSave" = false;
      "extensions.autoCheckUpdates" = false;
      "extensions.autoUpdate" = false;
      "security.workspace.trust.enabled" = true;
      "telemetry.telemetryLevel" = "off";
      "update.mode" = "none";
      "workbench.enableExperiments" = false;
      "[c]" = {
        "editor.defaultFormatter" = "llvm-vs-code-extensions.vscode-clangd";
        "editor.formatOnSave" = false;
      };
      "[cpp]" = {
        "editor.defaultFormatter" = "llvm-vs-code-extensions.vscode-clangd";
        "editor.formatOnSave" = false;
      };
    }
  );

  workspace = pkgs.writeText "CMSC-216.code-workspace" (
    builtins.toJSON {
      folders = [
        {
          name = "216-sync";
          path = "${localRoot}/216-sync";
        }
      ];
      extensions = {
        recommendations = [
          "llvm-vs-code-extensions.vscode-clangd"
          "PhilipDaoud.sftp-neo"
        ];
        unwantedRecommendations = [
          "GitHub.copilot"
          "GitHub.copilot-chat"
          "OpenAI.chatgpt"
          "anthropic.claude-code"
          "Continue.continue"
        ];
      };
      settings = {
        "clangd.fallbackFlags" = [
          "-std=c11"
          "-Wall"
          "-Wextra"
        ];
        "editor.rulers" = [ 80 ];
        "files.exclude" = {
          "**/.DS_Store" = true;
          "**/*.o" = true;
        };
        "search.exclude" = {
          "**/.git" = true;
          "**/.cmsc216-sftp-backups" = true;
        };
      };
      tasks = {
        version = "2.0.0";
        tasks =
          map
            (task: {
              inherit (task) label args;
              type = "process";
              command = "${cli}/bin/cmsc216";
              options.cwd = "\${workspaceFolder:216-sync}";
              presentation = {
                reveal = "always";
                panel = "dedicated";
                clear = false;
              };
              problemMatcher = [ ];
            })
            [
              {
                label = "CMSC 216: Doctor";
                args = [ "doctor" ];
              }
              {
                label = "CMSC 216: Sync to Zaratan";
                args = [ "sync" ];
              }
              {
                label = "CMSC 216: Test on Zaratan";
                args = [ "test" ];
              }
              {
                label = "CMSC 216: Zaratan Shell";
                args = [ "shell" ];
              }
              {
                label = "CMSC 216: Exam Check";
                args = [ "exam-check" ];
              }
            ];
      };
    }
  );

  sftpConfig = pkgs.writeText "cmsc216-sftp.json" (
    builtins.toJSON {
      name = "CMSC 216 Zaratan";
      context = "216-sync";
      protocol = "sftp";
      host = "login.zaratan.umd.edu";
      port = 22;
      username = directoryId;
      remotePath = remoteRoot;
      privateKeyPath = identityFile;
      interactiveAuth = true;
      uploadOnSave = true;
      downloadOnOpen = false;
      useTempFile = false;
      openSsh = false;
      concurrency = 4;
      connectTimeout = 20000;
      keepalive = 30000;
      algorithms.serverHostKey = [ "ssh-ed25519" ];
      sshConfigPath = "/etc/ssh/ssh_config";
      ignore = [
        ".DS_Store"
        ".git/**"
        ".vscode/**"
        ".cmsc216-sftp-backups/**"
      ];
      watcher = {
        files = "**/*";
        autoUpload = false;
        autoDelete = false;
        autoRename = false;
      };
      syncOption = {
        delete = false;
        skipCreate = false;
        ignoreExisting = false;
        update = false;
      };
      backup = {
        enabled = true;
        location = "local";
        folder = "../.cmsc216-sftp-backups";
        versions = 5;
        onDelete = false;
      };
      hooks = {
        preUpload = "${cli}/bin/cmsc216 vpn-if-needed";
        preSync = "${cli}/bin/cmsc216 vpn-if-needed";
      };
    }
  );

  infoPlist = pkgs.writeText "CMSC-216-Info.plist" ''
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
      <key>CFBundleDisplayName</key>
      <string>CMSC 216</string>
      <key>CFBundleExecutable</key>
      <string>CMSC216</string>
      <key>CFBundleIconFile</key>
      <string>CMSC216.icns</string>
      <key>CFBundleIdentifier</key>
      <string>com.therealrishabh.cmsc216</string>
      <key>CFBundleName</key>
      <string>CMSC 216</string>
      <key>CFBundlePackageType</key>
      <string>APPL</string>
      <key>CFBundleShortVersionString</key>
      <string>2026.1</string>
      <key>CFBundleVersion</key>
      <string>1</string>
      <key>LSMinimumSystemVersion</key>
      <string>14.0</string>
      <key>NSHighResolutionCapable</key>
      <true/>
    </dict>
    </plist>
  '';

  launcher = pkgs.writeShellScript "CMSC216" ''
    set -eu
    mkdir -p ${lib.escapeShellArg localRoot} ${lib.escapeShellArg "${localRoot}/216-sync"} ${lib.escapeShellArg dataRoot}
    exec ${managedVscodium}/bin/codium \
      --user-data-dir ${lib.escapeShellArg dataRoot} \
      --new-window \
      ${workspace} \
      "$@"
  '';

  app = pkgs.runCommand "cmsc216-app-2026.1" { } ''
    app="$out/Applications/CMSC 216.app"
    mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    cp ${infoPlist} "$app/Contents/Info.plist"
    cp ${launcher} "$app/Contents/MacOS/CMSC216"
    chmod 0755 "$app/Contents/MacOS/CMSC216"
    ln -s \
      ${pkgs.vscodium}/Applications/VSCodium.app/Contents/Resources/VSCodium.icns \
      "$app/Contents/Resources/CMSC216.icns"
  '';
in
{
  inherit
    app
    cli
    managedVscodium
    settings
    sftpConfig
    sftpNeo
    workspace
    ;
}
