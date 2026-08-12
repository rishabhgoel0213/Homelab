{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.mach1Additive;
  modelName = "mach1-additive-35b";
  modelState = "${config.homelab.paths.stateRoot}/local-models/${modelName}";
  package = import ../../packages/mach1-additive.nix { inherit pkgs; };
in
{
  options.homelab.mach1Additive = {
    enable = lib.mkEnableOption "Mach-1 Additive 35B local GPU inference";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8000;
      description = "Loopback port for the Mach-1 OpenAI-compatible API.";
    };

    contextWindow = lib.mkOption {
      type = lib.types.ints.positive;
      default = 65536;
      description = "Context window allocated by the Mach-1 WebGPU engine.";
    };

    maxTokens = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4096;
      description = "Maximum completion size advertised to Pi.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ package.downloader ];

    systemd.tmpfiles.rules = [
      "d ${config.homelab.paths.stateRoot}/local-models 0750 rishabh users - -"
      "d ${modelState} 0750 rishabh users - -"
    ];

    systemd.services.mach1-additive-download = {
      description = "Download and verify the pinned Mach-1 Additive 35B checkpoint";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        User = "rishabh";
        Group = "users";
        ExecStart = "${package.downloader}/bin/mach1-additive-download ${modelState}";
        TimeoutStartSec = "2h";
      };
    };

    virtualisation.oci-containers.containers.${modelName} = {
      image = "mach1-additive-35b:nix";
      imageFile = package.image;
      autoStart = false;
      environment = {
        MODEL_DIR = "/models";
        MACH1_HOST = "127.0.0.1";
        MACH1_PORT = toString cfg.port;
        MACH1_MAX_CONTEXT = toString cfg.contextWindow;
        MACH1_MAX_TOKENS = toString cfg.maxTokens;
      };
      volumes = [
        "${modelState}:/models:ro"
        "/nix/store:/nix/store:ro"
        "/run/opengl-driver:/run/opengl-driver:ro"
      ];
      # Host networking avoids this host's Tailscale exit-node capture of the
      # Docker bridge. MACH1_HOST keeps the API loopback-only.
      extraOptions = [
        "--network=host"
        "--device=nvidia.com/gpu=all"
      ];
    };

    systemd.services.docker-mach1-additive-35b = {
      after = [ "nvidia-container-toolkit-cdi-generator.service" ];
      unitConfig.ConditionPathExists = "${modelState}/.mach1-manifest.json";
    };

    homelab.pi.localModels.${modelName} = {
      displayName = "Mach-1 Additive 35B";
      baseUrl = "http://127.0.0.1:${toString cfg.port}/v1";
      contextWindow = cfg.contextWindow;
      maxTokens = cfg.maxTokens;
      reasoning = true;
      serviceUnit = "docker-mach1-additive-35b.service";
      fetchUnit = "mach1-additive-download.service";
      healthUrl = "http://127.0.0.1:${toString cfg.port}/health";
      compat.supportsReasoningEffort = true;
    };

    assertions = [
      {
        assertion = config.virtualisation.docker.enable;
        message = "homelab.mach1Additive.enable requires virtualisation.docker.enable.";
      }
      {
        assertion = config.hardware.nvidia-container-toolkit.enable;
        message = "homelab.mach1Additive.enable requires the NVIDIA container toolkit.";
      }
      {
        assertion = cfg.maxTokens < cfg.contextWindow;
        message = "homelab.mach1Additive.maxTokens must be smaller than contextWindow.";
      }
    ];
  };
}
