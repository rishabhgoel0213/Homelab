{
  lib,
  pkgs,
  directoryId,
  localRoot,
  remoteRoot,
  dataRoot,
  codiumBin,
  authPersist ? "8h",
}:

let
  cli = pkgs.writeShellApplication {
    name = "cmsc216";
    runtimeInputs = [
      pkgs.clang-tools
      pkgs.coreutils
      pkgs.gnugrep
      pkgs.python3
      pkgs.rsync
    ];
    text = ''
      export CMSC216_DIRECTORY_ID=${lib.escapeShellArg directoryId}
      export CMSC216_LOCAL_ROOT=${lib.escapeShellArg localRoot}
      export CMSC216_REMOTE_ROOT=${lib.escapeShellArg remoteRoot}
      export CMSC216_DATA_ROOT=${lib.escapeShellArg dataRoot}
      export CMSC216_CODIUM_BIN=${lib.escapeShellArg codiumBin}
      export CMSC216_AUTH_PERSIST=${lib.escapeShellArg authPersist}
      export CMSC216_DOWNLOAD_SCRIPT=${./bin/download-lab.py}

      ${builtins.readFile ./bin/cmsc216}
    '';
  };

  settings = {
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
  };

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
                label = "CMSC 216: Download Next Lab";
                args = [ "next-lab" ];
              }
              {
                label = "CMSC 216: Download Next Project";
                args = [ "next-project" ];
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

in
{
  inherit
    cli
    settings
    workspace
    ;
}
