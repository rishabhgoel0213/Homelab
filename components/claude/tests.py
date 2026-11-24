"""Validate retired MCP pruning and signed-release rejection boundary."""
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
    config = Path(temporary) / ".claude.json"
    config.write_text(json.dumps({
        "oauthAccount": {"test": "preserve"},
        "mcpServers": {
            "custom": {"command": "keep"},
            "codex-scheduler": {"command": "drop"},
            "zen-live": {"command": "drop"},
        },
    }))
    subprocess.run(["python3", str(root / "prune-mcp.py"), str(config), "codex-scheduler", "tasks", "zen-live"], check=True)
    pruned = json.loads(config.read_text())
    assert pruned["oauthAccount"] == {"test": "preserve"}
    assert set(pruned["mcpServers"]) == {"custom"}
