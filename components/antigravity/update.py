"""Pin the Antigravity CLI and T3's ACP runtime, validating before tools/auto-update commits.

The CLI follows Google's latest manifests. The ACP runtime follows the exact
release bundled in the pinned T3 package, because T3 supports only tested
runtime versions.
"""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

MANIFESTS = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests"
CLI_URL = r"https://storage\.googleapis\.com/antigravity-public/antigravity-cli/{version}-[0-9]+/{path}"
PLATFORMS = {"linux": ("linux_amd64", "linux-x64/cli_linux_x64.tar.gz"), "mac": ("darwin_arm64", "darwin-arm/cli_mac_arm64.tar.gz")}
ACP_ENTRY = re.compile(
    rb'\["linux-x64",\s*\{\s*version:\s*ANTIGRAVITY_RELEASE_VERSION,\s*'
    rb'url:\s*"(https://dl\.google\.com/agy-extensions/releases/linux/agy-acp-server-([0-9]+\.[0-9]+\.[0-9]+)-linux-x86_64\.zip)",\s*'
    rb'sha256:\s*"([0-9a-f]{64})"'
)
ACP_VERSION = re.compile(rb'ANTIGRAVITY_RELEASE_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"')


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def sri(algorithm, digest):
    return f"{algorithm}-" + base64.b64encode(bytes.fromhex(digest)).decode()


def cli_release(name, manifest):
    platform, path = PLATFORMS[name]
    version = manifest.get("version", "")
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), f"bad {platform} version"
    assert re.fullmatch(CLI_URL.format(version=re.escape(version), path=re.escape(path)), manifest.get("url", "")), f"bad {platform} url"
    assert re.fullmatch(r"[0-9a-f]{128}", manifest.get("sha512", "")), f"bad {platform} sha512"
    return version, manifest["url"], sri("sha512", manifest["sha512"])


def acp_release(binary):
    """Return (version, url, SRI hash) of the linux-x64 runtime a T3 binary installs."""
    entries = set(ACP_ENTRY.findall(binary))
    versions = set(ACP_VERSION.findall(binary))
    assert len(entries) == 1 and len(versions) == 1, "T3 Antigravity runtime pin not found exactly once"
    url, version, digest = entries.pop()
    assert version == versions.pop(), "T3 Antigravity runtime URL and version disagree"
    return version.decode(), url.decode(), sri("sha256", digest.decode())


def render(cli, acp):
    (version, linux_url, linux_hash), (_, mac_url, mac_hash) = cli["linux"], cli["mac"]
    acp_version, acp_url, acp_hash = acp
    return (
        "{\n"
        f'  version = "{version}";\n'
        f'  linuxUrl = "{linux_url}";\n'
        f'  linuxHash = "{linux_hash}";\n'
        f'  macUrl = "{mac_url}";\n'
        f'  macHash = "{mac_hash}";\n'
        f'  acpVersion = "{acp_version}";\n'
        f'  acpUrl = "{acp_url}";\n'
        f'  acpHash = "{acp_hash}";\n'
        "}\n"
    )


def nix_build(repo, installable, *flags):
    return subprocess.check_output(["nix", "build", "--impure", "--no-link", *flags, installable], cwd=repo, text=True).strip()


def main(target):
    if target != "latest":
        sys.exit("Google publishes only the latest Antigravity CLI manifest; use 'latest'.")
    state = json.loads(fetch("http://100.73.159.103:1022/state"))
    assert state.get("schema") == 1 and state.get("state") == "unbricked"
    assert state.get("latchedBricked") is False and type(state.get("ageSeconds")) in (int, float)
    assert 0 <= state["ageSeconds"] <= 3, "Brick state must be fresh"
    repo = Path(os.environ.get("HOMELAB_DEV_ROOT", "/home/rishabh/Projects/Homelab"))
    cli = {name: cli_release(name, json.loads(fetch(f"{MANIFESTS}/{platform}.json"))) for name, (platform, _) in PLATFORMS.items()}
    assert cli["linux"][0] == cli["mac"][0], "Linux and Mac CLI releases differ; retry later"
    t3 = Path(nix_build(repo, ".#t3code", "--print-out-paths"))
    acp = acp_release((t3 / "libexec/t3code/t3").read_bytes())
    pin = repo / "components/antigravity/release.nix"
    manifest = repo / "components/darwin-deploy/artifacts.nix"
    original = {p: p.read_text() for p in (pin, manifest)}
    candidates = {pin: render(cli, acp)}
    if candidates[pin] == original[pin]:
        return
    try:
        pin.write_text(candidates[pin])
        mac = nix_build(repo, ".#macbook-antigravity", "--print-out-paths")
        assert re.fullmatch(r"/nix/store/[a-z0-9]{32}-antigravity-cli-darwin-[0-9.]+", mac)
        updated, count = re.subn(r'antigravity = "[^"]+";', f'antigravity = "{mac}";', original[manifest])
        assert count == 1, "artifacts.nix must pin antigravity exactly once"
        assert manifest.read_text() == original[manifest]
        candidates[manifest] = updated
        manifest.write_text(updated)
        nix_build(repo, ".#nixosConfigurations.nixos-pc.config.system.build.toplevel")
    except BaseException:
        for path, candidate in candidates.items():
            if path.read_text() == candidate:
                path.write_text(original[path])
        raise


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "latest")
