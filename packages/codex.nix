{
  codex,
  fetchFromGitHub,
  lib,
  rustPlatform,
}:

let
  version = "0.145.0";
  srcHash = "sha256-/r4mBoJhHB1v5NTA4Hk565/D5B0deYJf9xJW330hyf0=";
  cargoHash = "sha256-t9IMRK9R+Z67ThEcgBI0HQU0E4aJHcOjKp22RFclh9U=";
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
})
