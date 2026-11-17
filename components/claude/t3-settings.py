"""Merge managed Claude executable settings without replacing other T3 preferences."""
import json
import os
from pathlib import Path
import sys
import tempfile

path = Path(sys.argv[1])
settings = json.loads(path.read_text()) if path.exists() else {}
provider = settings.setdefault("providers", {}).setdefault("claudeAgent", {})
provider.update(binaryPath="/run/current-system/sw/bin/claude", homePath="/srv/state/claude")
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
    json.dump(settings, stream, indent=2)
    stream.write("\n")
    temporary = stream.name
os.replace(temporary, path)
