"""Translate portable Codex MCP definitions to Antigravity's mcp_config.json shape."""
import json
import sys
import tomllib
from pathlib import Path


def stdio(entry):
    return {k: entry[k] for k in ("command", "args", "env") if k in entry}


config = tomllib.loads(Path(sys.argv[1]).read_text())
servers = {}
for name, entry in config.get("mcp_servers", {}).items():
    if entry.get("enabled", True) is False:
        continue
    if "command" in entry:
        servers[name] = stdio(entry)
    elif "url" in entry:
        servers[name] = {"serverUrl": entry["url"]}
        if "http_headers" in entry:
            servers[name]["headers"] = entry["http_headers"]
for plugin in sys.argv[2:]:
    for name, entry in json.loads(Path(plugin).read_text()).get("mcpServers", {}).items():
        if "command" in entry:
            servers[name] = stdio(entry)
        else:
            servers[name] = {"serverUrl": entry["url"], **({"headers": entry["headers"]} if "headers" in entry else {})}
print(json.dumps({"mcpServers": servers}, indent=2))
