{
  codex,
  fetchFromGitHub,
  fetchurl,
  lib,
  rustPlatform,
}:

let
  version = "0.147.0";
  srcHash = "sha256-NKeOxp9vLcx7tpghqhpS3ocPqUDP2PircNwkJNpHBPo=";
  cargoHash = "sha256-MJuM2QLxvL+r/Gw8QXLjtsLS25QGVCqcqU5GJssSoQ4=";
  rustyV8Version = "150.4.0";
  rustyV8Archive = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rusty-v8-v${rustyV8Version}/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz";
    hash = "sha256-o1x10fJuapg4haRbM0kKTr5U8FBQVosyuJz7QhswtYM=";
  };
  rustyV8Binding = fetchurl {
    url = "https://github.com/openai/codex/releases/download/rusty-v8-v${rustyV8Version}/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs";
    hash = "sha256-dyeCauR5vbZF6Acjn7EtH44uI956bPFvXuWSaQ0dhQY=";
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
    inherit pname version src sourceRoot;
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
