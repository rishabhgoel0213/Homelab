"""Point T3's Antigravity provider at the Nix ACP runtime; keep other preferences.

The runtime's store path is used, not /run/current-system: activation runs before
that link switches, and a changed path makes T3 re-probe after each update.
"""
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
# Enable once; T3 keeps this flag on the instance, and a later disable in its
# provider settings is respected.
if "enabled" not in instance and "enabled" not in config:
    instance["enabled"] = True
config["binaryPath"] = sys.argv[2]
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
    json.dump(settings, stream, indent=2)
    stream.write("\n")
    temporary = stream.name
os.replace(temporary, path)
