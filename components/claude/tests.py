"""Validate the portable MCP translation and signed-release rejection boundary."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).parent
spec = importlib.util.spec_from_file_location("client", root / "mac-client.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
for bad in ({}, {"schema": 1, "target": "darwin-arm64", "storePath": "/tmp/claude", "version": "1.0.0"}):
    try:
        client.validate_release(bad)
    except RuntimeError:
        pass
    else:
        raise AssertionError("accepted untrusted release path")
with tempfile.TemporaryDirectory() as temporary:
    config = Path(temporary) / "config.toml"
    config.write_text('[mcp_servers.local]\ncommand="/bin/tool"\nargs=["mcp"]\nrequired=false\n[mcp_servers.off]\ncommand="off"\nenabled=false\n[mcp_servers.remote]\nurl="https://example.com/mcp"\n')
    translated = json.loads(subprocess.check_output(["python3", str(root / "mcp.py"), str(config)], text=True))
    assert translated == {"mcpServers": {"local": {"type": "stdio", "command": "/bin/tool", "args": ["mcp"]}, "remote": {"type": "http", "url": "https://example.com/mcp"}}}
with tempfile.TemporaryDirectory() as temporary:
    config = Path(temporary) / ".claude.json"
    mcp = Path(temporary) / "mcp.json"
    config.write_text(json.dumps({"oauthAccount": {"test": "preserve"}, "mcpServers": {"custom": {"command": "keep"}}}))
    mcp.write_text(json.dumps({"mcpServers": {"shared": {"command": "add"}}}))
    subprocess.run(["python3", str(root / "install-mcp.py"), str(config), str(mcp)], check=True)
    merged = json.loads(config.read_text())
    assert merged["oauthAccount"] == {"test": "preserve"}
    assert set(merged["mcpServers"]) == {"custom", "shared"}
