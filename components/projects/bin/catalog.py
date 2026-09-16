"""Read-only, private RSS views of the projectctl inventory."""

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

spec = importlib.util.spec_from_file_location("projectctl", os.environ["PROJECTCTL_SOURCE"])
projectctl = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = projectctl
spec.loader.exec_module(projectctl)


def render(category, categories):
    if category not in categories:
        raise KeyError(category)
    defaults = {name: key for key, names in categories.items() for name in names}
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    for key, value in {
        "title": f"Projects: {category}",
        "link": os.environ["PROJECTCTL_JUPYTER_URL"],
        "description": "Active projects, grouped by organization.category",
    }.items():
        ET.SubElement(channel, key).text = value
    for project in sorted(projectctl.discover_projects(), key=lambda p: (p.title.casefold(), p.id)):
        organization = project.manifest.get("organization", {})
        if not isinstance(organization, dict):
            raise ValueError(f"Invalid organization metadata: {project.name}")
        selected = organization.get("category", defaults.get(project.name, "uncategorized"))
        if not isinstance(selected, str):
            raise ValueError(f"Invalid category: {project.name}")
        if selected not in categories:
            selected = "uncategorized"
        if selected != category:
            continue
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = project.title
        ET.SubElement(item, "link").text = projectctl.jupyter_url(project)
        ET.SubElement(item, "guid", isPermaLink="false").text = project.id
        # Stable date: Zen's RSS provider requires one even with timeRange=0.
        ET.SubElement(item, "pubDate").text = format_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        category = path.removeprefix("/feeds/").removesuffix(".xml")
        if path != f"/feeds/{category}.xml" or category not in self.server.categories:
            self.send_error(404)
            return
        try:
            body = render(category, self.server.categories)
        except Exception:
            # A failure must not become an empty feed: retain Zen's last good list.
            self.log_error("Project inventory unavailable")
            self.send_error(503, "Project inventory unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8796), Handler)
    server.categories = json.loads(Path(sys.argv[1]).read_text())
    server.serve_forever()
