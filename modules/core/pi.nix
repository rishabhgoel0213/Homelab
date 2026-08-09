{
  config,
  lib,
  pkgs,
  ...
}:

let
  homelab = config.homelab;
  cfg = homelab.pi;
  piAgentDir = homelab.paths.piAgentDir;
  piPackage = pkgs.callPackage ../../packages/pi-coding-agent.nix { };
  piCourierPackage = pkgs.callPackage ../../packages/pi-courier.nix { };
  piCourierState = "${homelab.paths.stateRoot}/pi/courier";
  piCourierSessions = "${piCourierState}/sessions";
  piBin = "${piPackage}/bin/pi";
  piWrapper = pkgs.writeShellScriptBin "pi" ''
    export PI_CODING_AGENT_DIR=${lib.escapeShellArg piAgentDir}
    export HOME=${lib.escapeShellArg homelab.paths.userHome}
    exec ${piBin} "$@"
  '';
  piRpcShim = pkgs.writeText "pi-courier-rpc-shim.mjs" ''
    import { spawn } from "node:child_process";

    const child = spawn(
      ${builtins.toJSON piBin},
      [
        "--model",
        ${builtins.toJSON cfg.courier.model},
        "--thinking",
        ${builtins.toJSON cfg.courier.thinkingLevel},
        ...process.argv.slice(2),
      ],
      {
        env: { ...process.env, HOME: ${builtins.toJSON homelab.paths.userHome} },
        stdio: "inherit",
      },
    );

    for (const signal of ["SIGINT", "SIGTERM"]) {
      process.on(signal, () => child.kill(signal));
    }
    child.on("exit", (code, signal) => {
      if (signal) process.kill(process.pid, signal);
      else process.exit(code ?? 1);
    });
  '';
  enabledLocalModels = lib.filterAttrs (_: model: model.enable) cfg.localModels;
  localModels = lib.mapAttrsToList (id: model: {
    inherit (model)
      api
      baseUrl
      contextWindow
      maxTokens
      reasoning
      ;
    inherit id;
    name = model.displayName;
    input = model.input;
    cost = {
      input = 0;
      output = 0;
      cacheRead = 0;
      cacheWrite = 0;
    };
    compat = {
      inherit (model.compat)
        supportsDeveloperRole
        supportsReasoningEffort
        supportsStore
        supportsUsageInStreaming
        ;
    };
  }) enabledLocalModels;
  modelsJson = pkgs.writeText "pi-models.json" (
    builtins.toJSON {
      providers = lib.optionalAttrs (localModels != [ ]) {
        homelab-local = {
          baseUrl = "http://127.0.0.1";
          api = "openai-completions";
          apiKey = "homelab-local";
          models = localModels;
        };
      };
    }
  );
  localModelRegistry = pkgs.writeText "homelab-local-models.json" (
    builtins.toJSON (
      lib.mapAttrs (id: model: {
        inherit (model)
          enable
          fetchUnit
          healthUrl
          serviceUnit
          ;
        inherit id;
      }) cfg.localModels
    )
  );
  localModelDoctor = pkgs.writeShellApplication {
    name = "local-model-doctor";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.curl
      pkgs.jq
      pkgs.systemd
    ];
    text = ''
      registry=/etc/homelab/local-models.json
      requested="''${1:-}"
      failed=0
      found=0

      while IFS= read -r row; do
        id="$(jq -r '.key' <<<"$row")"
        if [[ -n "$requested" && "$requested" != "$id" ]]; then
          continue
        fi
        found=1
        enabled="$(jq -r '.value.enable' <<<"$row")"
        unit="$(jq -r '.value.serviceUnit // empty' <<<"$row")"
        health="$(jq -r '.value.healthUrl // empty' <<<"$row")"
        if [[ "$enabled" != true ]]; then
          printf '%s: disabled\n' "$id"
          continue
        fi
        if [[ -n "$unit" ]] && ! systemctl is-active --quiet "$unit"; then
          printf '%s: service %s is not active\n' "$id" "$unit" >&2
          failed=1
          continue
        fi
        if [[ -n "$health" ]] && ! curl --fail --silent --show-error "$health" >/dev/null; then
          printf '%s: health check failed: %s\n' "$id" "$health" >&2
          failed=1
          continue
        fi
        printf '%s: ready\n' "$id"
      done < <(jq -c 'to_entries[]' "$registry")

      if [[ "$found" == 0 ]]; then
        printf 'unknown local model: %s\n' "$requested" >&2
        exit 2
      fi
      exit "$failed"
    '';
  };
  preparePiHome = pkgs.writeShellScript "prepare-pi-home" ''
    set -euo pipefail

    install -d -m 0700 -o rishabh -g users \
      ${lib.escapeShellArg "${homelab.paths.stateRoot}/pi"} \
      ${lib.escapeShellArg piAgentDir} \
      ${lib.escapeShellArg "${piAgentDir}/sessions"} \
      ${lib.escapeShellArg "${piAgentDir}/extensions"} \
      ${lib.escapeShellArg "${piAgentDir}/skills"} \
      ${lib.escapeShellArg "${piAgentDir}/prompts"}

    install -m 0600 -o rishabh -g users \
      ${../../pi/settings.json} \
      ${lib.escapeShellArg "${piAgentDir}/settings.json"}
    install -m 0600 -o rishabh -g users \
      ${modelsJson} \
      ${lib.escapeShellArg "${piAgentDir}/models.json"}
    install -m 0600 -o rishabh -g users \
      ${../../pi/AGENTS.md} \
      ${lib.escapeShellArg "${piAgentDir}/AGENTS.md"}
    install -m 0600 -o rishabh -g users \
      ${../../pi/extensions/agent-history.ts} \
      ${lib.escapeShellArg "${piAgentDir}/extensions/agent-history.ts"}
  '';
in
{
  options.homelab.pi = {
    courier = {
      enable = lib.mkEnableOption "full-access Pi agent over private Matrix";
      model = lib.mkOption {
        type = lib.types.str;
        default = "openai-codex/gpt-5.6-sol";
        description = "Pi provider/model used by the Matrix Courier session.";
      };
      thinkingLevel = lib.mkOption {
        type = lib.types.enum [
          "off"
          "minimal"
          "low"
          "medium"
          "high"
          "xhigh"
          "max"
        ];
        default = "medium";
        description = "Pi thinking level used by the Matrix Courier session.";
      };
      trustedMatrixUser = lib.mkOption {
        type = lib.types.str;
        default = "@rishabh:${homelab.domain}";
        description = "Only Matrix user authorized to send direct messages to Courier.";
      };
    };

    localModels = lib.mkOption {
      default = { };
      description = "Local models exposed to Pi through the shared homelab-local provider.";
      type = lib.types.attrsOf (
        lib.types.submodule (
          { name, ... }:
          {
            options = {
              enable = lib.mkOption {
                type = lib.types.bool;
                default = true;
                description = "Whether Pi advertises this local model.";
              };
              displayName = lib.mkOption {
                type = lib.types.str;
                default = name;
                description = "Human-readable model name in Pi.";
              };
              baseUrl = lib.mkOption {
                type = lib.types.str;
                description = "OpenAI-compatible endpoint ending in /v1.";
              };
              api = lib.mkOption {
                type = lib.types.enum [
                  "anthropic-messages"
                  "google-generative-ai"
                  "openai-completions"
                  "openai-responses"
                ];
                default = "openai-completions";
                description = "Pi API adapter used for this model.";
              };
              contextWindow = lib.mkOption {
                type = lib.types.ints.positive;
                description = "Context window advertised to Pi.";
              };
              maxTokens = lib.mkOption {
                type = lib.types.ints.positive;
                description = "Maximum output tokens advertised to Pi.";
              };
              reasoning = lib.mkOption {
                type = lib.types.bool;
                default = false;
                description = "Whether the model exposes Pi reasoning levels.";
              };
              input = lib.mkOption {
                type = lib.types.listOf (
                  lib.types.enum [
                    "image"
                    "text"
                  ]
                );
                default = [ "text" ];
                description = "Input modalities accepted by the model.";
              };
              serviceUnit = lib.mkOption {
                type = lib.types.nullOr lib.types.str;
                default = null;
                description = "Optional systemd unit checked by local-model-doctor.";
              };
              fetchUnit = lib.mkOption {
                type = lib.types.nullOr lib.types.str;
                default = null;
                description = "Optional checkpoint-fetch unit used by the ops runbook.";
              };
              healthUrl = lib.mkOption {
                type = lib.types.nullOr lib.types.str;
                default = null;
                description = "Optional HTTP endpoint checked by local-model-doctor.";
              };
              compat = {
                supportsDeveloperRole = lib.mkOption {
                  type = lib.types.bool;
                  default = false;
                };
                supportsReasoningEffort = lib.mkOption {
                  type = lib.types.bool;
                  default = false;
                };
                supportsStore = lib.mkOption {
                  type = lib.types.bool;
                  default = false;
                };
                supportsUsageInStreaming = lib.mkOption {
                  type = lib.types.bool;
                  default = true;
                };
              };
            };
          }
        )
      );
    };
  };

  config = {
    environment.systemPackages = [
      piWrapper
      localModelDoctor
    ]
    ++ lib.optional cfg.courier.enable piCourierPackage;

    environment.etc."homelab/local-models.json".source = localModelRegistry;

    environment.sessionVariables = {
      PI_CODING_AGENT_DIR = piAgentDir;
    };

    sops.templates."pi-courier.env" = lib.mkIf cfg.courier.enable {
      owner = "rishabh";
      group = "users";
      mode = "0400";
      content = ''
        PI_MATRIX_ACCESS_TOKEN=${config.sops.placeholder."matrix-pi-courier-access-token"}
      '';
    };

    systemd.services.pi-state = {
      description = "Prepare the managed Pi coding-agent state";
      wantedBy = [ "multi-user.target" ];
      restartIfChanged = true;
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = preparePiHome;
      };
    };

    systemd.tmpfiles.rules = lib.optionals cfg.courier.enable [
      "d ${piCourierState} 0700 rishabh users - -"
      "d ${piCourierSessions} 0700 rishabh users - -"
    ];

    systemd.services.pi-courier = lib.mkIf cfg.courier.enable {
      description = "Full-access Pi coding agent over private Matrix";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      requires = [
        "matrix-synapse.service"
        "pi-state.service"
      ];
      after = [
        "caddy.service"
        "matrix-synapse.service"
        "network-online.target"
        "pi-state.service"
        "sops-nix.service"
      ];
      path = with pkgs; [
        bash
        coreutils
        curl
        fd
        findutils
        git
        gnugrep
        jq
        nodejs_24
        openssh
        ripgrep
        rsync
        sudo
        systemd
        util-linux
      ];
      environment = {
        HOME = piCourierState;
        PI_CLI_PATH = toString piRpcShim;
        PI_CODING_AGENT_DIR = piAgentDir;
        PI_CODING_AGENT_SESSION_DIR = piCourierSessions;
        PI_LOG_LEVEL = "info";
        PI_MATRIX_ENCRYPTION = "true";
        PI_MATRIX_HOMESERVER = "https://matrix.${homelab.internalDomain}";
        PI_MATRIX_TRUSTED_USERS = cfg.courier.trustedMatrixUser;
        PI_WORKDIR = "/etc/agents";
      };
      serviceConfig = {
        User = "rishabh";
        Group = "users";
        EnvironmentFile = config.sops.templates."pi-courier.env".path;
        WorkingDirectory = "/etc/agents";
        ExecStart = "${piCourierPackage}/bin/pi-courier run";
        Restart = "always";
        RestartSec = "5s";
        UMask = "0077";
      };
      restartTriggers = [ piRpcShim ];
    };

    systemd.services.pi-auto-update = {
      description = "Automatically update the managed Pi package";
      wants = [ "network-online.target" ];
      after = [
        "network-online.target"
        "codex-auto-update.service"
      ];
      path = with pkgs; [
        bash
        coreutils
        gawk
        git
        gnugrep
        jq
        nix
        nixos-rebuild
        perl
        sudo
        systemd
        util-linux
      ];
      environment = {
        PI_OPS_ROOT = homelab.paths.opsRoot;
        HOST = config.networking.hostName;
      };
      serviceConfig = {
        Type = "oneshot";
        WorkingDirectory = homelab.paths.opsRoot;
        ExecStart = "${homelab.paths.opsRoot}/scripts/pi-auto-update";
      };
    };

    systemd.timers.pi-auto-update = {
      description = "Daily managed Pi package update";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "*-*-* 05:30:00";
        Persistent = true;
        RandomizedDelaySec = "10m";
        Unit = "pi-auto-update.service";
      };
    };

    assertions = lib.optionals cfg.courier.enable [
      {
        assertion = homelab.matrix.enable;
        message = "homelab.pi.courier.enable requires homelab.matrix.enable.";
      }
      {
        assertion = homelab.secrets.enable;
        message = "homelab.pi.courier.enable requires homelab.secrets.enable.";
      }
    ];
  };
}
