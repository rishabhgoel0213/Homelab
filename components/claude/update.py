"""Pin both official platforms and validate before committing via tools/auto-update."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request


def fetch(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read()


state = json.loads(fetch("http://100.73.159.103:1022/state"))
assert state.get("schema") == 1 and state.get("state") == "unbricked"
assert state.get("latchedBricked") is False and type(state.get("ageSeconds")) in (int, float)
assert 0 <= state["ageSeconds"] <= 3, "Brick state must be fresh"
repo = Path(os.environ.get("HOMELAB_DEV_ROOT", "/home/rishabh/Projects/Homelab"))
base = "https://downloads.claude.ai/claude-code-releases"
version = sys.argv[1]
if version == "latest":
    version = fetch(base + "/latest").decode().strip()
assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
pin = repo / "components/claude/release.nix"
manifest = repo / "components/darwin-deploy/artifacts.nix"
if f'version = "{version}";' in pin.read_text():
    sys.exit(0)
release = json.loads(fetch(f"{base}/{version}/manifest.json"))
def hash_for(platform):
    value = release["platforms"][platform]["checksum"]
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    return "sha256-" + base64.b64encode(bytes.fromhex(value)).decode()
original = {p: p.read_text() for p in (pin, manifest)}
candidates = {}
try:
    candidates[pin] = '{\n  version = "' + version + '";\n  linuxHash = "' + hash_for("linux-x64") + '";\n  macHash = "' + hash_for("darwin-arm64") + '";\n}\n'
    pin.write_text(candidates[pin])
    mac = subprocess.check_output(["nix", "build", "--impure", "--no-link", "--print-out-paths", ".#macbook-claude"], cwd=repo, text=True).strip()
    assert re.fullmatch(r"/nix/store/[a-z0-9]{32}-claude-code-darwin-[0-9.]+", mac)
    candidates[manifest] = re.sub(r'claude = "[^"]+";', f'claude = "{mac}";', original[manifest])
    assert manifest.read_text() == original[manifest]
    manifest.write_text(candidates[manifest])
    subprocess.run(["nix", "build", "--impure", "--no-link", ".#nixosConfigurations.nixos-pc.config.system.build.toplevel"], cwd=repo, check=True)
except BaseException:
    for path, candidate in candidates.items():
        if path.read_text() == candidate:
            path.write_text(original[path])
    raise
