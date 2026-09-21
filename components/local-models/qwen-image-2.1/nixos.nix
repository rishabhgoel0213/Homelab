{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.homelab.qwenImage21;
  modelName = "qwen-image-2.1";
  modelState = "${config.homelab.paths.stateRoot}/local-models/${modelName}";
  unstablePkgs = import inputs.nixpkgs-unstable {
    system = pkgs.system;
    config = {
      allowUnfree = true;
      cudaCapabilities = [ "8.6" ];
    };
  };
  package = import ./package.nix { inherit pkgs unstablePkgs; };
in
{
  options.homelab.qwenImage21 = {
    enable = lib.mkEnableOption "Qwen-Image 2.1 local image editing";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8188;
      description = "Loopback port for the Qwen-Image ComfyUI API.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      package.cli
      package.downloader
    ];

    systemd.tmpfiles.rules = [
      "d ${config.homelab.paths.stateRoot}/local-models 0750 rishabh users - -"
      "d ${modelState} 0750 rishabh users - -"
      "d ${modelState}/custom_nodes 0750 rishabh users - -"
      "d ${modelState}/input 0750 rishabh users - -"
      "d ${modelState}/output 0750 rishabh users - -"
      "d ${modelState}/temp 0750 rishabh users - -"
      "d ${modelState}/user 0750 rishabh users - -"
      "d ${modelState}/models 0750 rishabh users - -"
    ];

    systemd.services."qwen-image-2.1-download" = {
      description = "Download and verify the pinned Qwen-Image 2.1 checkpoint";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      environment.QWEN_IMAGE_LICENSE_ACCEPTED = "qwen-research";
      serviceConfig = {
        Type = "oneshot";
        User = "rishabh";
        Group = "users";
        ExecStart = "${package.downloader}/bin/qwen-image-2.1-download ${modelState}/models";
        TimeoutStartSec = "6h";
      };
    };

    systemd.services."qwen-image-2.1" = {
      description = "Qwen-Image 2.1 local image editing API";
      after = [ "nvidia-container-toolkit-cdi-generator.service" ];
      conflicts = [
        "docker-bonsai-ternary-27b.service"
        "docker-mach1-additive-35b.service"
        "docker-nemotron-3.5-lightning-30b-a3b.service"
      ];
      unitConfig.ConditionPathExists = [
        "${modelState}/models/.qwen-image-2.1-manifest.json"
        "${modelState}/models/diffusion_models/qwen_image_2.1_int8_convrot.safetensors"
        "${modelState}/models/text_encoders/qwen3vl_8b_int8_convrot.safetensors"
        "${modelState}/models/vae/qwen_image_2.1_vae_bf16.safetensors"
      ];
      environment = {
        CUDA_MODULE_LOADING = "LAZY";
        LD_LIBRARY_PATH = "/run/opengl-driver/lib";
        PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True";
      };
      serviceConfig = {
        User = "rishabh";
        Group = "users";
        WorkingDirectory = modelState;
        ExecStart = lib.concatStringsSep " " [
          "${package.comfyui}/bin/comfyui"
          "--base-directory=${modelState}"
          "--database-url=sqlite:///${modelState}/user/comfyui.db"
          "--listen=127.0.0.1"
          "--port=${toString cfg.port}"
          "--disable-auto-launch"
          "--disable-metadata"
          "--disable-fast-disk"
        ];
        Restart = "on-failure";
        RestartSec = 3;
        TimeoutStartSec = "5min";
      };
    };

    assertions = [
      {
        assertion = config.hardware.nvidia-container-toolkit.enable;
        message = "homelab.qwenImage21.enable requires the NVIDIA driver/toolkit configuration.";
      }
    ];
  };
}
