"""Validate MCP translation, T3 settings merge, release pin parsing and Mac release checks."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, root / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


client = load("client", "mac-client.py")
for bad in (
    {},
    {"schema": 1, "target": "darwin-arm64", "storePath": "/tmp/agy", "version": "1.0.0"},
    {"schema": 1, "target": "darwin-arm64", "storePath": "/nix/store/" + "a" * 32 + "-antigravity-cli-darwin-1.0.0", "version": "2.0.0"},
):
    try:
        client.validate_release(bad)
    except RuntimeError:
        pass
    else:
        raise AssertionError("accepted untrusted release")
good = "/nix/store/" + "a" * 32 + "-antigravity-cli-darwin-1.5.14"
assert str(client.validate_release({"schema": 1, "target": "darwin-arm64", "storePath": good, "version": "1.5.14"})) == good

update = load("update", "update.py")
digest = "ab" * 32
blob = (
    b'ANTIGRAVITY_RELEASE_VERSION = "1.4.5";\n["linux-x64", {\n\t\t\tversion: ANTIGRAVITY_RELEASE_VERSION,\n'
    b'\t\t\turl: "https://dl.google.com/agy-extensions/releases/linux/agy-acp-server-1.4.5-linux-x86_64.zip",\n'
    b'\t\t\tsha256: "' + digest.encode() + b'",'
)
acp = update.acp_release(blob * 2)
assert acp == ("1.4.5", "https://dl.google.com/agy-extensions/releases/linux/agy-acp-server-1.4.5-linux-x86_64.zip", update.sri("sha256", digest))
for broken in (b"", blob.replace(b'= "1.4.5"', b'= "1.4.6"'), blob + blob.replace(b"ab", b"cd")):
    try:
        update.acp_release(broken)
    except AssertionError:
        pass
    else:
        raise AssertionError("accepted ambiguous or missing T3 runtime pin")
linux = {"version": "1.5.14", "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.5.14-123/linux-x64/cli_linux_x64.tar.gz", "sha512": "0f" * 64}
assert update.cli_release("linux", linux)[2].startswith("sha512-")
for field, value in (("version", '1.5.14";'), ("url", "https://example.com/cli_linux_x64.tar.gz"), ("sha512", "0f")):
    try:
        update.cli_release("linux", {**linux, field: value})
    except AssertionError:
        pass
    else:
        raise AssertionError(f"accepted malformed manifest {field}")
rendered = update.render({"linux": update.cli_release("linux", linux), "mac": ("1.5.14", "https://mac", "sha512-m")}, acp)
assert 'version = "1.5.14";' in rendered.splitlines()[1] and 'acpVersion = "1.4.5";' in rendered

with tempfile.TemporaryDirectory() as temporary:
    config = Path(temporary) / "config.toml"
    plugin = Path(temporary) / ".mcp.json"
    config.write_text('[mcp_servers.local]\ncommand="/bin/tool"\nargs=["mcp"]\nrequired=false\n[mcp_servers.off]\ncommand="off"\nenabled=false\n[mcp_servers.remote]\nurl="https://example.com/mcp"\nhttp_headers={A="b"}\n')
    plugin.write_text(json.dumps({"mcpServers": {"canvas": {"command": "/bin/canvas"}}}))
    translated = json.loads(subprocess.check_output(["python3", str(root / "mcp.py"), str(config), str(plugin)], text=True))
    assert translated == {"mcpServers": {
        "local": {"command": "/bin/tool", "args": ["mcp"]},
        "remote": {"serverUrl": "https://example.com/mcp", "headers": {"A": "b"}},
        "canvas": {"command": "/bin/canvas"},
    }}

with tempfile.TemporaryDirectory() as temporary:
    settings = Path(temporary) / "settings.json"
    settings.write_text(json.dumps({"idleCompaction": True, "providerInstances": {
        "claudeAgent": {"driver": "claudeAgent", "config": {"binaryPath": "/bin/claude"}},
        "antigravity": {"driver": "antigravity", "config": {"enabled": False, "authMethod": "gemini-api-key"}},
    }}))
    subprocess.run(["python3", str(root / "t3-settings.py"), str(settings)], check=True)
    merged = json.loads(settings.read_text())
    assert merged["idleCompaction"] is True
    assert merged["providerInstances"]["claudeAgent"]["config"] == {"binaryPath": "/bin/claude"}
    assert merged["providerInstances"]["antigravity"]["config"] == {
        "enabled": False, "authMethod": "gemini-api-key", "binaryPath": "/run/current-system/sw/bin/agy-acp-server"}
    settings.write_text("{}")
    subprocess.run(["python3", str(root / "t3-settings.py"), str(settings)], check=True)
    assert json.loads(settings.read_text())["providerInstances"]["antigravity"] == {
        "driver": "antigravity", "config": {"enabled": True, "binaryPath": "/run/current-system/sw/bin/agy-acp-server"}}
