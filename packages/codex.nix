{
  codex,
  fetchFromGitHub,
  lib,
  rustPlatform,
}:

let
  version = "0.146.1";
  srcHash = "sha256-aXK/hUz61STkD8xcVqvBzP1RYDu+kw7v1ufVZHyzN84=";
  cargoHash = "sha256-N9jbH/cgAyu2QxneSnpkdaF0MgV3ZtDmN9q6rr9u+hE=";
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
