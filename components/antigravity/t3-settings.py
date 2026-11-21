"""Point T3's Antigravity provider at the Nix ACP runtime; keep other preferences."""
import json
import os
from pathlib import Path
import sys
import tempfile

path = Path(sys.argv[1])
settings = json.loads(path.read_text()) if path.exists() else {}
instance = settings.setdefault("providerInstances", {}).setdefault("antigravity", {})
instance["driver"] = "antigravity"
config = instance.setdefault("config", {})
# Enable once; a later disable in T3's provider settings is respected.
config.setdefault("enabled", True)
config["binaryPath"] = "/run/current-system/sw/bin/agy-acp-server"
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
    json.dump(settings, stream, indent=2)
    stream.write("\n")
    temporary = stream.name
os.replace(temporary, path)
