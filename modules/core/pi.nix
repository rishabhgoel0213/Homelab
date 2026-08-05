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
  piBin = "${piPackage}/bin/pi";
  piWrapper = pkgs.writeShellScriptBin "pi" ''
    export PI_CODING_AGENT_DIR=${lib.escapeShellArg piAgentDir}
    export HOME=${lib.escapeShellArg homelab.paths.userHome}
    exec ${piBin} "$@"
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
  options.homelab.pi.localModels = lib.mkOption {
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

  config = {
    environment.systemPackages = [
      piWrapper
      localModelDoctor
    ];

    environment.etc."homelab/local-models.json".source = localModelRegistry;

    environment.sessionVariables = {
      PI_CODING_AGENT_DIR = piAgentDir;
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
  };
}
