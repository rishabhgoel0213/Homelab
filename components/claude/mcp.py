"""Translate portable Codex MCP definitions; omit Codex-specific policy keys."""
import json
import sys
import tomllib
from pathlib import Path

config = tomllib.loads(Path(sys.argv[1]).read_text())
servers = {}
for name, entry in config.get("mcp_servers", {}).items():
    if entry.get("enabled", True) is False:
        continue
    if "command" in entry:
        servers[name] = {"type": "stdio", **{k: entry[k] for k in ("command", "args", "env") if k in entry}}
    elif "url" in entry:
        servers[name] = {"type": "http", "url": entry["url"]}
        if "http_headers" in entry:
            servers[name]["headers"] = entry["http_headers"]
for plugin in sys.argv[2:]:
    servers.update(json.loads(Path(plugin).read_text()).get("mcpServers", {}))
print(json.dumps({"mcpServers": servers}, indent=2))
