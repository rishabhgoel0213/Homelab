{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.nemotronLightning;
  modelName = "nemotron-3.5-lightning-30b-a3b";
  modelState = "${config.homelab.paths.stateRoot}/local-models/${modelName}";
  package = import ../../packages/nemotron-lightning.nix { inherit pkgs; };
  containerService = "docker-${modelName}";
  containerUnit = "${containerService}.service";
in
{
  options.homelab.nemotronLightning = {
    enable = lib.mkEnableOption "Nemotron 3.5 Lightning 30B-A3B local GPU inference";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8003;
      description = "Loopback port for the Pi-compatible Nemotron API.";
    };

    backendPort = lib.mkOption {
      type = lib.types.port;
      default = 8004;
      description = "Loopback port for the vLLM backend.";
    };

    contextWindow = lib.mkOption {
      type = lib.types.ints.positive;
      default = 262144;
      description = "Context window allocated by vLLM for Nemotron.";
    };

    maxTokens = lib.mkOption {
      type = lib.types.ints.positive;
      default = 8192;
      description = "Maximum completion size advertised to Pi.";
    };

    cpuOffloadGiB = lib.mkOption {
      type = lib.types.ints.positive;
      default = 12;
      description = "Pinned host memory made available for vLLM expert-weight offload.";
    };

    gpuMemoryUtilization = lib.mkOption {
      type = lib.types.float;
      default = 0.9;
      description = "Fraction of GPU memory vLLM may reserve.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ package.downloader ];

    systemd.tmpfiles.rules = [
      "d ${config.homelab.paths.stateRoot}/local-models 0750 rishabh users - -"
      "d ${modelState} 0750 rishabh users - -"
    ];

    systemd.services.nemotron-lightning-download = {
      description = "Download and verify the pinned Nemotron 3.5 Lightning checkpoint";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        User = "rishabh";
        Group = "users";
        ExecStart = "${package.downloader}/bin/nemotron-lightning-download ${modelState}";
        TimeoutStartSec = "4h";
      };
    };

    virtualisation.oci-containers.containers.${modelName} = {
      image = "vllm/vllm-openai@sha256:c2f3b1b964e47809b722b5e75b61b1e7b39a50f70388cf2bf2418f16a9f31da2";
      autoStart = false;
      environment = {
        LIBRARY_PATH = "/usr/local/nvidia/lib64:/usr/local/cuda/lib64";
        TORCH_CUDA_ARCH_LIST = "8.6";
      };
      cmd = [
        "--model"
        "/models"
        "--served-model-name"
        modelName
        "--host"
        "127.0.0.1"
        "--port"
        (toString cfg.backendPort)
        "--max-model-len"
        (toString cfg.contextWindow)
        "--max-num-seqs"
        "1"
        "--max-num-batched-tokens"
        "4096"
        "--gpu-memory-utilization"
        (toString cfg.gpuMemoryUtilization)
        "--cpu-offload-gb"
        (toString cfg.cpuOffloadGiB)
        "--cpu-offload-params"
        "experts"
        "--quantization"
        "modelopt_fp4"
        "--moe-backend"
        "humming"
        "--linear-backend"
        "humming"
        "--mamba-backend"
        "flashinfer"
        "--mamba-cache-mode"
        "align"
        "--mamba-ssu-algorithm"
        "simple"
        "--enable-prefix-caching"
        "--async-scheduling"
        "--reasoning-parser"
        "nemotron_v3"
        "--tool-call-parser"
        "qwen3_coder"
        "--enable-auto-tool-choice"
      ];
      volumes = [ "${modelState}:/models:ro" ];
      extraOptions = [
        "--network=host"
        "--ipc=host"
        "--device=nvidia.com/gpu=all"
      ];
    };

    systemd.services.${containerService} = {
      after = [ "nvidia-container-toolkit-cdi-generator.service" ];
      conflicts = [
        "docker-bonsai-ternary-27b.service"
        "docker-mach1-additive-35b.service"
      ];
      unitConfig.ConditionPathExists = "${modelState}/.nemotron-lightning-manifest.json";
    };

    systemd.services.nemotron-lightning = {
      description = "Pi-compatible proxy for Nemotron 3.5 Lightning";
      requires = [ containerUnit ];
      partOf = [ containerUnit ];
      wantedBy = [ containerUnit ];
      after = [ containerUnit ];
      serviceConfig = {
        User = "rishabh";
        Group = "users";
        ExecStart = "${package.proxy}/bin/nemotron-lightning-proxy";
        Restart = "on-failure";
        RestartSec = 2;
      };
      environment = {
        NEMOTRON_HOST = "127.0.0.1";
        NEMOTRON_PORT = toString cfg.port;
        NEMOTRON_BACKEND_PORT = toString cfg.backendPort;
        NEMOTRON_MODEL = modelName;
      };
    };

    homelab.pi.localModels.${modelName} = {
      displayName = "Nemotron 3.5 Lightning 30B-A3B (W4A16)";
      baseUrl = "http://127.0.0.1:${toString cfg.port}/v1";
      contextWindow = cfg.contextWindow;
      maxTokens = cfg.maxTokens;
      reasoning = true;
      serviceUnit = "nemotron-lightning.service";
      fetchUnit = "nemotron-lightning-download.service";
      healthUrl = "http://127.0.0.1:${toString cfg.port}/health";
      compat.supportsReasoningEffort = true;
    };

    assertions = [
      {
        assertion = config.virtualisation.docker.enable;
        message = "homelab.nemotronLightning.enable requires virtualisation.docker.enable.";
      }
      {
        assertion = config.hardware.nvidia-container-toolkit.enable;
        message = "homelab.nemotronLightning.enable requires the NVIDIA container toolkit.";
      }
      {
        assertion = cfg.maxTokens < cfg.contextWindow;
        message = "homelab.nemotronLightning.maxTokens must be smaller than contextWindow.";
      }
      {
        assertion = cfg.port != cfg.backendPort;
        message = "Nemotron proxy and backend ports must differ.";
      }
      {
        assertion = cfg.gpuMemoryUtilization > 0.0 && cfg.gpuMemoryUtilization < 1.0;
        message = "homelab.nemotronLightning.gpuMemoryUtilization must be between zero and one.";
      }
    ];
  };
}
