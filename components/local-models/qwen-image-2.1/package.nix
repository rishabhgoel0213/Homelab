{ pkgs, unstablePkgs }:

let
  source = pkgs.lib.cleanSource ./.;

  comfySource = pkgs.fetchFromGitHub {
    owner = "Comfy-Org";
    repo = "ComfyUI";
    tag = "v0.37.0";
    hash = "sha256-hfpoQsu8xzKHCy2Qqw2BMGsorwizJEuhKXWjUUJzTHs=";
  };

  cudaPackages = unstablePkgs.cudaPackages_13.overrideScope (_final: prev: {
    # This service consumes cuDNN's shared libraries. Stripping its enormous
    # unused static archives adds minutes to every uncached local build.
    cudnn = prev.cudnn.overrideAttrs (_old: { dontStrip = true; });

    # Torch links to NVSHMEM, but single-GPU inference needs neither its
    # cluster transports nor its very large test/benchmark executables.
    libnvshmem = (prev.libnvshmem.override {
      withGdrcopy = false;
      withIbgda = false;
      withLibfabric = false;
      withMpi = false;
      withNccl = false;
      withPmix = false;
      withUcx = false;
    }).overrideAttrs (old: {
      cmakeFlags = map (
        pkgs.lib.replaceStrings
          [ "NVSHMEM_BUILD_TESTS:BOOL=TRUE" "NVSHMEM_BUILD_EXAMPLES:BOOL=TRUE" ]
          [ "NVSHMEM_BUILD_TESTS:BOOL=FALSE" "NVSHMEM_BUILD_EXAMPLES:BOOL=FALSE" ]
      ) old.cmakeFlags;
    });
  });

  # Keep nixpkgs' CUDA-enabled Python/Torch foundation, while updating the two
  # native modules whose APIs changed between its ComfyUI 0.30.1 and 0.37.0.
  python = unstablePkgs.python3.override {
    self = python;
    packageOverrides = final: prev:
    let
      cudaBindings = prev.cuda-bindings.override { inherit cudaPackages; };
      tritonBin = prev.triton-bin.override { inherit cudaPackages; };
      torchBin = (prev.torch-bin.override {
        inherit cudaPackages;
        cuda-bindings = cudaBindings;
        triton = tritonBin;
      }).overridePythonAttrs (old: {
        pythonRelaxDeps = (old.pythonRelaxDeps or [ ]) ++ [ "setuptools" ];
        passthru = (old.passthru or { }) // {
          inherit cudaPackages;
          cudaCapabilities = [ "8.6" ];
        };
      });
      # Torchaudio's release version now trails PyTorch's, but PyTorch ships a
      # cu130 wheel for it in the same index used by the 2.12 Torch wheel.
      torchaudioBin = (prev.torchaudio-bin.override {
        inherit cudaPackages;
        torch-bin = torchBin;
      }).overridePythonAttrs (old: {
        version = "2.11.0+cu130";
        src = pkgs.fetchurl {
          url = "https://download.pytorch.org/whl/cu130/torchaudio-2.11.0%2Bcu130-cp314-cp314-manylinux_2_28_x86_64.whl";
          name = "torchaudio-2.11.0+cu130-cp314-cp314-linux_x86_64.whl";
          hash = "sha256-N4tJZxtYERSi0l1Ako8SoVCHL+rfEWaaY/Vz6Bx4AZo=";
        };
        pythonRelaxDeps = (old.pythonRelaxDeps or [ ]) ++ [ "torch" ];
      });
    in
    {
      # Nixpkgs' CUDA source build is intentionally uncached. Its patched
      # upstream wheels are reproducible and avoid compiling PyTorch locally.
      cuda-bindings = cudaBindings;
      torch = torchBin;
      torchaudio = torchaudioBin;
      triton = tritonBin;
      torchvision = prev.torchvision-bin.override {
        inherit cudaPackages;
        torch-bin = torchBin;
      };
    };
  };
  comfyKitchen = (python.pkgs.comfy-kitchen.override {
    cudaSupport = true;
  }).overridePythonAttrs (old: {
    version = "0.2.35";
    env = (old.env or { }) // { COMFY_CUDA_ARCHS = "86"; };
    src = pkgs.fetchFromGitHub {
      owner = "Comfy-Org";
      repo = "comfy-kitchen";
      tag = "v0.2.35";
      fetchSubmodules = true;
      hash = "sha256-ymNZ4uuM59cOf+neC6tfr+NXH9f7LpF9ml7gsYfB4Fk=";
    };
  });
  comfyAimdo = python.pkgs.comfy-aimdo.overridePythonAttrs (old: {
    version = "0.5.5";
    src = pkgs.fetchFromGitHub {
      owner = "Comfy-Org";
      repo = "comfy-aimdo";
      tag = "v0.5.5";
      hash = "sha256-f5r2UgkWU49Y/sc9MBwlrmzaY3w4wcHJ0HgcFoVe3QY=";
    };
  });
  pythonEnv = python.withPackages (
    ps:
    (with ps; [
      aiohttp
      alembic
      av
      blake3
      comfy-angle
      comfyui-embedded-docs
      comfyui-frontend-package
      comfyui-workflow-templates
      einops
      filelock
      kornia
      numpy
      pillow
      psutil
      pydantic
      pydantic-settings
      pyopengl
      pyyaml
      requests
      safetensors
      scipy
      sentencepiece
      simpleeval
      spandrel
      sqlalchemy
      tokenizers
      torch
      torchaudio
      torchsde
      torchvision
      tqdm
      transformers
      yarl
    ])
    ++ [
      comfyAimdo
      comfyKitchen
    ]
  );

  comfyui = pkgs.stdenvNoCC.mkDerivation {
    pname = "comfyui";
    version = "0.37.0";
    src = comfySource;
    nativeBuildInputs = [ pkgs.makeBinaryWrapper ];
    installPhase = ''
      runHook preInstall
      mkdir -p $out/share/comfyui $out/bin
      cp -r . $out/share/comfyui
      makeBinaryWrapper ${pythonEnv}/bin/python $out/bin/comfyui \
        --add-flag "$out/share/comfyui/main.py" \
        --unset NIX_PYTHONPATH \
        --unset PYTHONPATH
      runHook postInstall
    '';
  };

  downloader = pkgs.writeShellApplication {
    name = "qwen-image-2.1-download";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.curl
      pkgs.jq
    ];
    text = ''
      exec ${pkgs.bash}/bin/bash ${source}/download-model.sh "$@"
    '';
  };

  cli = pkgs.writeShellApplication {
    name = "qwen-image-edit";
    runtimeInputs = [
      pkgs.fzf
      pkgs.python3
      pkgs.systemd
    ];
    text = ''
      exec python3 ${source}/qwen_image_edit.py "$@"
    '';
  };
in
{
  inherit cli comfyui downloader;
}
