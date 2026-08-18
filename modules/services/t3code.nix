{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (config) homelab;
  cfg = config.homelab.t3code;
  stateDir = homelab.paths.t3codeState;
  mobileStateDir = "${homelab.paths.stateRoot}/t3code-mobile";
  piAgentDir = homelab.paths.piAgentDir;
  updatesFqdn = "updates.${homelab.internalSubdomain}.${homelab.domain}";
  mobileUpdatesUrl = "https://${updatesFqdn}/api/manifest";
  package = pkgs.callPackage ../../packages/t3code.nix {
    inherit (cfg) revision sourceCheckout;
    inherit mobileUpdatesUrl;
  };
  desiredSettings = pkgs.writeText "t3code-settings.json" (
    builtins.toJSON {
      browserEditors = {
        jupyterLabUrl =
          if cfg.browserEditorUrls.jupyterlab == null then "" else cfg.browserEditorUrls.jupyterlab;
      };
      providers = {
        codex = {
          enabled = true;
          binaryPath = "/run/current-system/sw/bin/codex";
          homePath = homelab.paths.codexHome;
        };
        pi = {
          enabled = true;
          binaryPath = "/run/current-system/sw/bin/pi";
        };
      };
      providerInstances = {
        codex = {
          driver = "codex";
          enabled = true;
          displayName = "Codex";
          config = {
            binaryPath = "/run/current-system/sw/bin/codex";
            homePath = homelab.paths.codexHome;
          };
        };
        pi = {
          driver = "pi";
          enabled = true;
          displayName = "Pi";
          environment = [
            {
              name = "PI_CODING_AGENT_DIR";
              value = piAgentDir;
              sensitive = false;
            }
          ];
          config = {
            binaryPath = "/run/current-system/sw/bin/pi";
          };
        };
      };
    }
  );
  prepareState = pkgs.writeShellScript "prepare-t3code-state" ''
    set -euo pipefail

    dataDir=${lib.escapeShellArg "${stateDir}/userdata"}
    settingsPath="$dataDir/settings.json"
    settingsTmp="$dataDir/.settings.json.tmp"

    install -d -m 0700 -o rishabh -g users \
      ${lib.escapeShellArg stateDir} \
      "$dataDir"

    if [[ -s "$settingsPath" ]] && ${lib.getExe pkgs.jq} -e 'type == "object"' "$settingsPath" >/dev/null; then
      ${lib.getExe pkgs.jq} -s '.[0] * .[1]' \
        "$settingsPath" ${desiredSettings} > "$settingsTmp"
    else
      cp ${desiredSettings} "$settingsTmp"
    fi

    chown rishabh:users "$settingsTmp"
    chmod 0600 "$settingsTmp"
    mv "$settingsTmp" "$settingsPath"
  '';
in
{
  options.homelab.t3code = {
    enable = lib.mkEnableOption "T3 Code private coding-agent web UI";

    port = lib.mkOption {
      type = lib.types.port;
      default = 3773;
      description = "Loopback port used by the T3 Code server.";
    };

    mobileUpdatesPort = lib.mkOption {
      type = lib.types.port;
      default = 3774;
      description = "Loopback port used by the private Expo Updates server.";
    };

    sourceCheckout = lib.mkOption {
      type = lib.types.str;
      default = "/home/rishabh/Projects/t3code";
      description = "Canonical local checkout of the private T3 Code fork.";
    };

    revision = lib.mkOption {
      type = lib.types.strMatching "[0-9a-f]{40}";
      description = "Exact Git revision of the private T3 Code fork to build.";
    };

    browserEditorUrls.jupyterlab = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional JupyterLab origin advertised as a browser-based editor.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ package ];

    systemd.tmpfiles.rules = [
      "d ${stateDir} 0700 rishabh users - -"
      "d ${stateDir}/legacy-workspaces 0700 rishabh users - -"
      "d ${stateDir}/legacy-workspaces/homelab 0700 rishabh users - -"
      "d ${mobileStateDir} 0750 rishabh users - -"
    ];

    systemd.services.t3code = {
      description = "T3 Code coding-agent web UI";
      wantedBy = [ "multi-user.target" ];
      requires = [ "pi-state.service" ];
      wants = [ "network-online.target" ];
      after = [
        "network-online.target"
        "pi-state.service"
      ];
      path = with pkgs; [
        bash
        coreutils
        fd
        findutils
        gh
        git
        gnugrep
        gnused
        jq
        just
        nix
        openssh
        ripgrep
      ];
      environment = {
        CODEX_HOME = homelab.paths.codexHome;
        HOME = homelab.paths.userHome;
        PI_CODING_AGENT_DIR = piAgentDir;
        PROJECTCTL_BIN = "/run/current-system/sw/bin/projectctl";
        SHELL = "${pkgs.bash}/bin/bash";
        T3CODE_PROJECTCTL_BIN = "/run/current-system/sw/bin/projectctl";
        T3CODE_PROJECTS_ROOT = homelab.paths.projectsRoot;
        T3CODE_HOME = stateDir;
      };
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        WorkingDirectory = stateDir;
        ExecStartPre = prepareState;
        ExecStart = "${package}/bin/t3code serve --host 127.0.0.1 --port ${toString cfg.port} --base-dir ${stateDir}";
        Restart = "on-failure";
        RestartSec = "5s";
        UMask = "0077";
      };
    };

    systemd.services.t3code-updates = {
      description = "Private Expo Updates server for T3 Code Android";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      serviceConfig = {
        Type = "simple";
        User = "rishabh";
        Group = "users";
        ExecStart = lib.concatStringsSep " " [
          "${pkgs.python3}/bin/python"
          (lib.escapeShellArg ../../scripts/t3code-updates-server.py)
          "--host 127.0.0.1"
          "--port ${toString cfg.mobileUpdatesPort}"
          "--updates-root ${lib.escapeShellArg "${package}/share/t3code/mobile-updates"}"
          "--bootstrap-apk ${lib.escapeShellArg "${mobileStateDir}/t3code-preview.apk"}"
          "--public-url ${lib.escapeShellArg "https://${updatesFqdn}"}"
        ];
        Restart = "on-failure";
        RestartSec = "5s";
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectHome = true;
        ProtectSystem = "strict";
      };
    };

    homelab.routes.t3code = {
      enable = true;
      host = "t3code";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.port}";
      description = "Private T3 Code UI for Codex and Pi projects";
    };

    homelab.routes.t3code-updates = {
      enable = true;
      host = "updates";
      visibility = "internal";
      upstream = "http://127.0.0.1:${toString cfg.mobileUpdatesPort}";
      description = "Private Expo OTA updates and bootstrap APK for T3 Code Android";
    };

    assertions = [
      {
        assertion = homelab.acme.enable;
        message = "homelab.t3code.enable requires homelab.acme.enable for trusted internal HTTPS.";
      }
      {
        assertion = builtins.pathExists cfg.sourceCheckout;
        message = "homelab.t3code.sourceCheckout must point to the canonical private T3 Code checkout.";
      }
    ];
  };
}
