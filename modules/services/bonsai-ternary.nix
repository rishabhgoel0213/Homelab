{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.bonsaiTernary;
  modelName = "bonsai-ternary-27b";
  modelState = "${config.homelab.paths.stateRoot}/local-models/${modelName}";
  package = import ../../packages/bonsai-ternary.nix { inherit pkgs; };
in
{
  options.homelab.bonsaiTernary = {
    enable = lib.mkEnableOption "Ternary Bonsai 27B local GPU inference";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8001;
      description = "Loopback port for the Bonsai llama.cpp API.";
    };

    contextWindow = lib.mkOption {
      type = lib.types.ints.positive;
      default = 100000;
      description = "Context window allocated by llama.cpp for Bonsai.";
    };

    maxTokens = lib.mkOption {
      type = lib.types.ints.positive;
      default = 8192;
      description = "Maximum completion size advertised to Pi.";
    };

    cacheType = lib.mkOption {
      type = lib.types.enum [
        "q4_0"
        "q8_0"
      ];
      default = "q4_0";
      description = "GPU KV cache type; q4_0 is the model publisher's 100k-context operating point.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ package.downloader ];

    systemd.tmpfiles.rules = [
      "d ${config.homelab.paths.stateRoot}/local-models 0750 rishabh users - -"
      "d ${modelState} 0750 rishabh users - -"
    ];

    systemd.services.bonsai-ternary-download = {
      description = "Download and verify the pinned Ternary Bonsai 27B checkpoint";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        User = "rishabh";
        Group = "users";
        ExecStart = "${package.downloader}/bin/bonsai-ternary-download ${modelState}";
        TimeoutStartSec = "2h";
      };
    };

    virtualisation.oci-containers.containers.${modelName} = {
      image = "bonsai-ternary-27b:nix";
      imageFile = package.image;
      autoStart = false;
      environment = {
        MODEL_DIR = "/models";
        BONSAI_HOST = "127.0.0.1";
        BONSAI_PORT = toString cfg.port;
        BONSAI_CONTEXT = toString cfg.contextWindow;
        BONSAI_CACHE_TYPE = cfg.cacheType;
      };
      volumes = [
        "${modelState}:/models:ro"
        "/nix/store:/nix/store:ro"
        "/run/opengl-driver:/run/opengl-driver:ro"
      ];
      extraOptions = [
        "--network=host"
        "--device=nvidia.com/gpu=all"
      ];
    };

    systemd.services.docker-bonsai-ternary-27b = {
      after = [ "nvidia-container-toolkit-cdi-generator.service" ];
      conflicts = [ "docker-mach1-additive-35b.service" ];
      unitConfig.ConditionPathExists = "${modelState}/.bonsai-manifest.json";
    };

    homelab.pi.localModels.${modelName} = {
      displayName = "Ternary Bonsai 27B";
      baseUrl = "http://127.0.0.1:${toString cfg.port}/v1";
      contextWindow = cfg.contextWindow;
      maxTokens = cfg.maxTokens;
      reasoning = true;
      serviceUnit = "docker-bonsai-ternary-27b.service";
      fetchUnit = "bonsai-ternary-download.service";
      healthUrl = "http://127.0.0.1:${toString cfg.port}/health";
      compat.supportsReasoningEffort = true;
    };

    assertions = [
      {
        assertion = config.virtualisation.docker.enable;
        message = "homelab.bonsaiTernary.enable requires virtualisation.docker.enable.";
      }
      {
        assertion = config.hardware.nvidia-container-toolkit.enable;
        message = "homelab.bonsaiTernary.enable requires the NVIDIA container toolkit.";
      }
      {
        assertion = cfg.maxTokens < cfg.contextWindow;
        message = "homelab.bonsaiTernary.maxTokens must be smaller than contextWindow.";
      }
      {
        assertion = !config.homelab.mach1Additive.enable || cfg.port != config.homelab.mach1Additive.port;
        message = "Bonsai and Mach-1 local model API ports must differ.";
      }
    ];
  };
}
