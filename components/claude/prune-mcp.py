"""Remove retired managed MCP server entries while preserving login and custom config."""
import json
import os
from pathlib import Path
import sys
import tempfile

path = Path(sys.argv[1])
retired = set(sys.argv[2:])
if not path.exists() or not retired:
    raise SystemExit(0)
config = json.loads(path.read_text())
servers = config.get("mcpServers")
if not isinstance(servers, dict):
    raise SystemExit(0)
changed = False
for name in retired:
    if name in servers:
        del servers[name]
        changed = True
if not changed:
    raise SystemExit(0)
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
    temporary = stream.name
os.replace(temporary, path)
