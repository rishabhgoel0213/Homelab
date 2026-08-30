{
  codex,
  fetchFromGitHub,
  fetchurl,
  lib,
  rustPlatform,
  stdenv,
}:

let
  version = "0.151.0";
  srcHash = "sha256-snrzA4W+vLqpPk3MS4xw9SszK1byCKo6ERz3JDgRZdA=";
  cargoHash = "sha256-r6ox0dUH1OBkD8sQApfANrGbWxKXLv2UNLJZzciJc3I=";
  rustyV8Version = "150.4.0";
  rustyV8LinuxArchiveHash = "sha256-o1x10fJuapg4haRbM0kKTr5U8FBQVosyuJz7QhswtYM=";
  rustyV8LinuxBindingHash = "sha256-dyeCauR5vbZF6Acjn7EtH44uI956bPFvXuWSaQ0dhQY=";
  rustyV8DarwinArchiveHash = "sha256-AK27SHmISMd1UEQcaGc6XoUpuOG3PqvN7iMss5tA9KE=";
  rustyV8DarwinBindingHash = "sha256-ylrfDPicmnCtRgrnNkiy/om3SqETs8t/dXtqArdYOU8=";
  rustyV8Target =
    if stdenv.hostPlatform.isLinux && stdenv.hostPlatform.isx86_64 then
      "x86_64-unknown-linux-gnu"
    else if stdenv.hostPlatform.isDarwin && stdenv.hostPlatform.isAarch64 then
      "aarch64-apple-darwin"
    else
      throw "The managed Codex package does not have rusty_v8 assets for ${stdenv.hostPlatform.system}";
  rustyV8Hashes = {
    "x86_64-unknown-linux-gnu" = {
      archive = rustyV8LinuxArchiveHash;
      binding = rustyV8LinuxBindingHash;
    };
    "aarch64-apple-darwin" = {
      archive = rustyV8DarwinArchiveHash;
      binding = rustyV8DarwinBindingHash;
    };
  };
  rustyV8Hash = rustyV8Hashes.${rustyV8Target};
  rustyV8Archive = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rusty-v8-v${rustyV8Version}/librusty_v8_ptrcomp_sandbox_release_${rustyV8Target}.a.gz";
    hash = rustyV8Hash.archive;
  };
  rustyV8Binding = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rusty-v8-v${rustyV8Version}/src_binding_ptrcomp_sandbox_release_${rustyV8Target}.rs";
    hash = rustyV8Hash.binding;
  };
in
codex.overrideAttrs (_old: rec {
  pname = "codex";
  inherit version;

  src = fetchFromGitHub {
    owner = "openai";
    repo = "codex";
    tag = "rust-v${version}";
    hash = srcHash;
  };

  sourceRoot = "${src.name}/codex-rs";

  cargoDeps = rustPlatform.fetchCargoVendor {
    inherit
      pname
      version
      src
      sourceRoot
      ;
    hash = cargoHash;
  };

  # Codex delegates code-mode shell execution to this companion process.
  # Keep both binaries in the package so a version bump cannot leave T3
  # sessions with a working app server but a broken shell bridge.
  cargoBuildFlags = [
    "--package"
    "codex-cli"
    "--package"
    "codex-code-mode-host"
  ];
  cargoCheckFlags = cargoBuildFlags;

  env = (_old.env or { }) // {
    RUSTY_V8_ARCHIVE = rustyV8Archive;
    RUSTY_V8_SRC_BINDING_PATH = rustyV8Binding;
  };

  postPatch = ''
    for webrtc_build_rs in "$cargoDepsCopy"/*/webrtc-sys-*/build.rs; do
      if [[ -e "$webrtc_build_rs" ]]; then
        substituteInPlace "$webrtc_build_rs" \
          --replace-fail "cargo:rustc-link-lib=static=webrtc" "cargo:rustc-link-lib=dylib=webrtc"
      fi
    done
    for cargo_toml_line in 'lto = "thin"' 'codegen-units = 1'; do
      if grep -Fq "$cargo_toml_line" Cargo.toml; then
        substituteInPlace Cargo.toml --replace-fail "$cargo_toml_line" ""
      fi
    done
  '';

  postInstall = (_old.postInstall or "") + ''
    test -x "$out/bin/codex-code-mode-host"
  '';
})
