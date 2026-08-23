{
  cargo-zigbuild,
  clang,
  cmake,
  fetchFromGitHub,
  fetchurl,
  gitMinimal,
  gzip,
  lib,
  libclang,
  llvm,
  macosSdk,
  pkg-config,
  rustPlatform,
  rustToolchain,
  stdenvNoCC,
  zig,
}:

let
  version = "0.149.0";
  target = "aarch64-apple-darwin";
  src = fetchFromGitHub {
    owner = "openai";
    repo = "codex";
    tag = "rust-v${version}";
    hash = "sha256-SMVTW/CcGz4xxyeFe3KUf3Ns6jp+2SRMTvtA2o2+y7Q=";
  };
  cargoDeps = rustPlatform.fetchCargoVendor {
    pname = "codex-darwin-cross";
    inherit src version;
    sourceRoot = "${src.name}/codex-rs";
    hash = "sha256-K58PL588Hhk75FyXgU6b8IEAco8FIz8oGd1S0WgOjyQ=";
  };
  rustyV8Version = "150.4.0";
  rustyV8Archive = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rusty-v8-v${rustyV8Version}/librusty_v8_ptrcomp_sandbox_release_${target}.a.gz";
    hash = "sha256-AK27SHmISMd1UEQcaGc6XoUpuOG3PqvN7iMss5tA9KE=";
  };
  rustyV8Binding = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rusty-v8-v${rustyV8Version}/src_binding_ptrcomp_sandbox_release_${target}.rs";
    hash = "sha256-ylrfDPicmnCtRgrnNkiy/om3SqETs8t/dXtqArdYOU8=";
  };
  unstripped = stdenvNoCC.mkDerivation {
    pname = "codex-darwin-cross";
    inherit
      cargoDeps
      src
      version
      ;

    sourceRoot = "${src.name}/codex-rs";

    nativeBuildInputs = [
      cargo-zigbuild
      clang
      cmake
      gitMinimal
      gzip
      libclang
      pkg-config
      rustPlatform.cargoSetupHook
      rustToolchain
      zig
    ];

    env = {
      LIBCLANG_PATH = "${lib.getLib libclang}/lib";
      RUSTY_V8_ARCHIVE = rustyV8Archive;
      RUSTY_V8_SRC_BINDING_PATH = rustyV8Binding;
      SDKROOT = macosSdk;
    };

    # CMake is needed by native Cargo dependencies, but the Codex workspace is
    # not itself a CMake project.
    dontUseCmakeConfigure = true;

    postPatch = ''
      for cargo_toml_line in 'lto = "thin"' 'codegen-units = 1'; do
        if grep -Fq "$cargo_toml_line" Cargo.toml; then
          substituteInPlace Cargo.toml --replace-fail "$cargo_toml_line" ""
        fi
      done
    '';

    buildPhase = ''
      runHook preBuild

      export HOME="$TMPDIR/home"
      export CARGO_HOME="$TMPDIR/cargo-home"
      mkdir -p "$HOME" "$CARGO_HOME"
      cargo zigbuild \
        --offline \
        --release \
        --target ${target} \
        --package codex-cli \
        --package codex-code-mode-host

      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall

      mkdir -p "$out/bin"
      install -m 0755 target/${target}/release/codex "$out/bin/codex"
      install -m 0755 \
        target/${target}/release/codex-code-mode-host \
        "$out/bin/codex-code-mode-host"

      runHook postInstall
    '';

    dontFixup = true;

    meta = {
      description = "Codex CLI cross-compiled for Apple silicon macOS";
      homepage = "https://github.com/openai/codex";
      license = lib.licenses.asl20;
      mainProgram = "codex";
      platforms = [ "x86_64-linux" ];
    };
  };
in
stdenvNoCC.mkDerivation {
  pname = "codex-darwin-cross";
  inherit version;

  src = unstripped;
  dontUnpack = true;
  dontFixup = true;

  nativeBuildInputs = [ llvm ];

  installPhase = ''
    runHook preInstall

    mkdir -p "$out"
    cp -a "$src/." "$out/"
    chmod -R u+w "$out"
    llvm-strip --strip-debug "$out/bin/codex" "$out/bin/codex-code-mode-host"

    runHook postInstall
  '';

  passthru = { inherit unstripped; };
  inherit (unstripped) meta;
}
