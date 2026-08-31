{
  lib,
  pkgs,
  directoryId,
  localRoot,
  remoteRoot,
  dataRoot,
  authPersist ? "8h",
}:

let
  managedExtensions = [ pkgs.vscode-extensions.llvm-vs-code-extensions.vscode-clangd ];

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
      export CMSC216_DATA_ROOT=${lib.escapeShellArg dataRoot}
      export CMSC216_CODIUM_BIN=${lib.escapeShellArg "${managedVscodium}/bin/codium"}
      export CMSC216_AUTH_PERSIST=${lib.escapeShellArg authPersist}

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
          name = "cmsc216";
          path = localRoot;
        }
      ];
      extensions = {
        recommendations = [
          "llvm-vs-code-extensions.vscode-clangd"
        ];
        unwantedRecommendations = [
          "GitHub.copilot"
          "GitHub.copilot-chat"
          "OpenAI.chatgpt"
          "anthropic.claude-code"
          "Continue.continue"
          "PhilipDaoud.sftp-neo"
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
              options.cwd = "\${workspaceFolder:cmsc216}";
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
                label = "CMSC 216: Authenticate with Duo";
                args = [ "auth" ];
              }
              {
                label = "CMSC 216: Authentication Status";
                args = [ "auth-status" ];
              }
              {
                label = "CMSC 216: Clear Cached Authentication";
                args = [ "auth-clear" ];
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
                label = "CMSC 216: Run Command on Zaratan";
                args = [
                  "run"
                  "bash"
                  "-lc"
                  "\${input:zaratanCommand}"
                ];
              }
              {
                label = "CMSC 216: Format Current File";
                args = [
                  "format"
                  "\${file}"
                ];
              }
              {
                label = "CMSC 216: Exam Check";
                args = [ "exam-check" ];
              }
            ];
        inputs = [
          {
            id = "zaratanCommand";
            type = "promptString";
            description = "Command to run in the matching Zaratan directory";
            default = "make test";
          }
        ];
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
    mkdir -p ${lib.escapeShellArg localRoot} ${lib.escapeShellArg dataRoot}
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
    workspace
    ;
}
