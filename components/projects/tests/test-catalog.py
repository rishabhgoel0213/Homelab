import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
from xml.etree import ElementTree as ET

spec = importlib.util.spec_from_file_location("catalog", os.environ["CATALOG_SCRIPT"])
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CatalogTests(unittest.TestCase):
    def test_http_failures_preserve_cached_inventory(self):
        server = catalog.ThreadingHTTPServer(("127.0.0.1", 0), catalog.Handler)
        server.categories = {"research": []}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with patch.object(catalog, "render", return_value=b"<rss/>"):
                with urlopen(base + "/feeds/research.xml", timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b"<rss/>")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
            for path, status in [("/feeds/research.xml", 503), ("/feeds/unknown.xml", 404),
                                 ("/project.toml", 404)]:
                with patch.object(catalog, "render", side_effect=ValueError("bad manifest")):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(base + path, timeout=5)
                    self.assertEqual(error.exception.code, status)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_membership_and_identity(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "PROJECTS_ROOT": directory,
            "PROJECTCTL_JUPYTER_URL": "https://lab.example.test",
            "PROJECTCTL_JUPYTER_ROOT": "/",
        }):
            root = Path(directory) / "example"
            root.mkdir()
            categories = {"research": ["example"], "writing": [], "uncategorized": []}
            initial = ET.fromstring(catalog.render("research", categories)).find("channel/item")
            self.assertIsNotNone(initial)
            self.assertIn("/lab/tree/", initial.findtext("link"))
            self.assertEqual(initial.findtext("guid"), ET.fromstring(
                catalog.render("research", categories)).findtext("channel/item/guid"))
            manifest = root / "project.toml"
            manifest.write_text('schema = 1\nid = "12345678-1234-4234-a234-123456789abc"\n'
                                'name = "example"\ntitle = "Example & tools"\nstatus = "active"\n'
                                'created_at = "2026-01-01T00:00:00Z"\n'
                                '[organization]\ncategory = "writing"\nlabels = ["test"]\n')
            self.assertIsNone(ET.fromstring(catalog.render("research", categories)).find("channel/item"))
            self.assertEqual(ET.fromstring(catalog.render("writing", categories)).findtext(
                "channel/item/title"), "Example & tools")
            manifest.write_text(manifest.read_text().replace('category = "writing"', 'category = "unknown"'))
            self.assertIsNotNone(ET.fromstring(catalog.render("uncategorized", categories)).find("channel/item"))
            manifest.write_text(manifest.read_text().replace('status = "active"', 'status = "archived"'))
            self.assertIsNone(ET.fromstring(catalog.render("uncategorized", categories)).find("channel/item"))
            manifest.write_text("not valid toml!")
            with self.assertRaises(Exception):
                catalog.render("research", categories)
            with self.assertRaises(KeyError):
                catalog.render("unknown", categories)


if __name__ == "__main__":
    unittest.main()
