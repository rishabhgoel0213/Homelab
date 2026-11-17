"""Merge portable MCP definitions while preserving Claude login and preferences."""
import json
import os
from pathlib import Path
import sys
import tempfile

path = Path(sys.argv[1])
config = json.loads(path.read_text()) if path.exists() else {}
config.setdefault("mcpServers", {}).update(json.loads(Path(sys.argv[2]).read_text())["mcpServers"])
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
    temporary = stream.name
os.replace(temporary, path)
