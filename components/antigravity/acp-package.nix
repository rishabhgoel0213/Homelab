{
  stdenvNoCC,
  fetchurl,
  python3,
  unzip,
}:
let
  release = import ./release.nix;
in
# Google's ACP runtime for T3's Antigravity driver. T3 accepts only exact,
# tested runtime versions, so update.py pins the one the T3 package bundles.
stdenvNoCC.mkDerivation {
  pname = "antigravity-acp-server";
  version = release.acpVersion;
  src = fetchurl {
    url = release.acpUrl;
    hash = release.acpHash;
  };
  nativeBuildInputs = [ unzip ];
  unpackPhase = ''
    unzip -q "$src" agy_acp_server.par localharness_external
  '';
  dontBuild = true;
  # The .par is an ELF stub with an appended Python archive; patching or
  # stripping would corrupt it. It runs unmodified through nix-ld, and the
  # harness is statically linked.
  dontStrip = true;
  dontFixup = true;
  installPhase = ''
    install -Dm755 agy_acp_server.par "$out/libexec/antigravity-acp/agy_acp_server.par"
    install -Dm755 localharness_external "$out/libexec/antigravity-acp/localharness_external"
    # Install the transparent ACP wrapper right beside localharness_external so
    # T3's sibling-harness check passes while every session receives AGENTS.md + User Memory.
    {
      echo "#!${python3}/bin/python3"
      tail -n +2 ${./acp-wrapper.py}
    } > "$out/libexec/antigravity-acp/agy-acp-wrapper"
    chmod 755 "$out/libexec/antigravity-acp/agy-acp-wrapper"
    mkdir -p "$out/bin"
    ln -s ../libexec/antigravity-acp/agy-acp-wrapper "$out/bin/agy-acp-server"
  '';
}
