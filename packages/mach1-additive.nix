{ pkgs }:

let
  lib = pkgs.lib;
  source = lib.cleanSource ../local-models/mach1;
  appSource = pkgs.stdenvNoCC.mkDerivation {
    pname = "mach1-additive-source";
    version = "2026-08-05";
    src = source;
    installPhase = ''
      runHook preInstall
      mkdir -p $out/share/mach1
      cp -r app vendor $out/share/mach1/
      runHook postInstall
    '';
  };
  server = pkgs.writeShellApplication {
    name = "mach1-additive-serve";
    runtimeInputs = [
      pkgs.nodejs_24
      pkgs.vulkan-tools
      pkgs.xkbcomp
      pkgs.xkeyboard-config
    ];
    text = ''
      export MACH1_APP_ROOT=${appSource}/share/mach1
      export PLAYWRIGHT_CORE=${pkgs.playwright-driver}
      export CHROMIUM_BIN=${pkgs.chromium}/bin/chromium
      export XVFB_BIN=${pkgs.xorg-server}/bin/Xvfb
      export XKB_CONFIG_ROOT=${pkgs.xkeyboard-config}/share/X11/xkb
      export VK_DRIVER_FILES="''${VK_DRIVER_FILES:-/run/opengl-driver/share/vulkan/icd.d/nvidia_icd.json}"
      export LD_LIBRARY_PATH="/run/opengl-driver/lib:${
        lib.makeLibraryPath [
          pkgs.vulkan-loader
          pkgs.libx11
          pkgs.libxext
          pkgs.libxcb
          pkgs.libxau
          pkgs.libxdmcp
          pkgs.stdenv.cc.cc.lib
        ]
      }:''${LD_LIBRARY_PATH:-}"
      ${pkgs.vulkan-tools}/bin/vulkaninfo --summary >&2
      exec node ${appSource}/share/mach1/app/server.mjs "$@"
    '';
  };
  downloader = pkgs.writeShellApplication {
    name = "mach1-additive-download";
    runtimeInputs = [ pkgs.nodejs_24 ];
    text = ''
      exec node ${source}/download-model.mjs "$@"
    '';
  };
  image = pkgs.dockerTools.buildLayeredImage {
    name = "mach1-additive-35b";
    tag = "nix";
    contents = [
      server
      pkgs.bash
      pkgs.dockerTools.fakeNss
    ];
    extraCommands = ''
      mkdir -m 1777 tmp
    '';
    config = {
      Entrypoint = [ "${server}/bin/mach1-additive-serve" ];
      Env = [
        "MODEL_DIR=/models"
        "MACH1_HOST=127.0.0.1"
        "MACH1_PORT=8000"
        "MACH1_MAX_CONTEXT=16384"
      ];
      ExposedPorts = {
        "8000/tcp" = { };
      };
    };
  };
in
{
  inherit
    appSource
    downloader
    image
    server
    ;
}
