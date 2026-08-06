{ pkgs }:

let
  lib = pkgs.lib;
  runtimeRevision = "9ca265a57f85f2117942490f421f64a226dd9847";
  source = lib.cleanSource ../local-models/bonsai;
  upstreamLlama = pkgs.llama-cpp.override {
    blasSupport = false;
    cudaSupport = true;
  };
  prismLlama = upstreamLlama.overrideAttrs (old: {
    pname = "llama-cpp-prism-bonsai";
    # llama.cpp emits LLAMA_BUILD_NUMBER as a C++ integer literal.
    version = "9599";
    src = pkgs.fetchFromGitHub {
      owner = "PrismML-Eng";
      repo = "llama.cpp";
      rev = runtimeRevision;
      hash = "sha256-AATH4Bg0nhbuftEA1xcwAX0geVNmuBY5UWK5u2vgEYI=";
    };
    nativeBuildInputs = builtins.filter (
      input: input != pkgs.nodejs && input != pkgs.npmHooks.npmConfigHook
    ) old.nativeBuildInputs;
    npmDepsHash = "sha256-pjdbI6NcZRlJVd62xhgbLhWrwFYwgsIwjORqvo1+VD8=";
    preConfigure = ''
      prependToVar cmakeFlags "-DLLAMA_BUILD_COMMIT:STRING=${lib.substring 0 8 runtimeRevision}"
    '';
    cmakeFlags = old.cmakeFlags ++ [
      "-DCMAKE_CUDA_ARCHITECTURES=86"
      "-DLLAMA_BUILD_UI=OFF"
      "-DLLAMA_USE_PREBUILT_UI=OFF"
    ];
  });
  downloader = pkgs.writeShellApplication {
    name = "bonsai-ternary-download";
    runtimeInputs = [
      pkgs.bash
      pkgs.coreutils
      pkgs.curl
      pkgs.jq
    ];
    text = ''
      exec bash ${source}/download-model.sh "$@"
    '';
  };
  server = pkgs.writeShellApplication {
    name = "bonsai-ternary-serve";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.nodejs_24
      prismLlama
    ];
    text = ''
      model="''${MODEL_DIR:?MODEL_DIR must be set}/Ternary-Bonsai-27B-Q2_0.gguf"
      test -r "$model"
      backend_port="''${BONSAI_BACKEND_PORT:-8002}"
      export LD_LIBRARY_PATH="/run/opengl-driver/lib:${
        lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]
      }:''${LD_LIBRARY_PATH:-}"
      llama-server \
        --model "$model" \
        --alias bonsai-ternary-27b \
        --host 127.0.0.1 \
        --port "$backend_port" \
        --ctx-size "''${BONSAI_CONTEXT:-100000}" \
        --n-gpu-layers 99 \
        --parallel 1 \
        --batch-size 2048 \
        --ubatch-size 512 \
        --flash-attn on \
        --cache-type-k "''${BONSAI_CACHE_TYPE:-q4_0}" \
        --cache-type-v "''${BONSAI_CACHE_TYPE:-q4_0}" \
        --reasoning-format deepseek \
        --jinja \
        --metrics &
      backend_pid=$!

      export BONSAI_BACKEND_PORT="$backend_port"
      node ${source}/proxy.mjs &
      proxy_pid=$!

      # shellcheck disable=SC2329 # invoked indirectly by trap
      cleanup() {
        kill "$backend_pid" "$proxy_pid" 2>/dev/null || true
        wait "$backend_pid" "$proxy_pid" 2>/dev/null || true
      }
      trap cleanup EXIT INT TERM
      set +e
      wait -n "$backend_pid" "$proxy_pid"
      status=$?
      set -e
      exit "$status"
    '';
  };
  image = pkgs.dockerTools.buildLayeredImage {
    name = "bonsai-ternary-27b";
    tag = "nix";
    contents = [
      server
      pkgs.bash
      pkgs.dockerTools.fakeNss
    ];
    config = {
      Entrypoint = [ "${server}/bin/bonsai-ternary-serve" ];
      Env = [
        "MODEL_DIR=/models"
        "BONSAI_HOST=127.0.0.1"
        "BONSAI_PORT=8001"
        "BONSAI_CONTEXT=100000"
        "BONSAI_CACHE_TYPE=q4_0"
        "BONSAI_BACKEND_PORT=8002"
      ];
      ExposedPorts = {
        "8001/tcp" = { };
      };
    };
  };
in
{
  inherit
    downloader
    image
    prismLlama
    runtimeRevision
    server
    ;
}
