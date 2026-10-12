#!/usr/bin/env python3
"""Exercise the file-serving and confinement behavior over real HTTP."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from yarl import URL

SCRIPT = Path(os.environ.get("PROJECT_PAGES_SCRIPT", Path(__file__).parents[1] / "bin/project-pages.py"))
spec = importlib.util.spec_from_file_location("project_pages", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProjectPagesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "Projects"
        self.project = self.root / "A project"
        self.project.mkdir(parents=True)
        self.page = self.project / "PROJECT.html"
        self.page.write_text("<!doctype html><h1>Project π</h1>")
        self.client = TestClient(TestServer(module.create_app(self.root)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_nested_html_head_and_query(self):
        response = await self.client.get("/A%20project/PROJECT.html?refresh=1")
        self.assertEqual(response.status, 200)
        self.assertIn("Project π", await response.text())
        self.assertEqual(response.content_type, "text/html")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")
        head = await self.client.head("/A%20project/PROJECT.html")
        self.assertEqual(head.status, 200)
        self.assertEqual(head.headers["Content-Length"], response.headers["Content-Length"])
        self.assertEqual(await head.read(), b"")

    async def test_no_directory_listing_or_missing_file_fallback(self):
        for path in ("/", "/A%20project/", "/missing", "/A%20project/missing.html"):
            response = await self.client.get(path, headers={"Accept": "application/json"})
            self.assertEqual(response.status, 404, path)
            self.assertNotIn("PROJECT.html", await response.text())

    async def test_existing_index_and_relative_asset(self):
        (self.project / "index.html").write_text('<img src="diagram.svg">')
        (self.project / "diagram.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        response = await self.client.get("/A%20project?x=1", allow_redirects=False)
        self.assertEqual(response.status, 308)
        self.assertEqual(response.headers["Location"], "/A%20project/?x=1")
        self.assertEqual((await self.client.get("/A%20project/")).status, 200)
        asset = await self.client.get("/A%20project/diagram.svg")
        self.assertEqual(asset.status, 200)
        self.assertEqual(asset.content_type, "image/svg+xml")

    async def test_range_revalidation_and_new_file_contents(self):
        response = await self.client.get("/A%20project/PROJECT.html")
        etag = response.headers["ETag"]
        cached = await self.client.get("/A%20project/PROJECT.html", headers={"If-None-Match": etag})
        self.assertEqual(cached.status, 304)
        partial = await self.client.get("/A%20project/PROJECT.html", headers={"Range": "bytes=0-8"})
        self.assertEqual(partial.status, 206)
        self.assertEqual(await partial.read(), self.page.read_bytes()[:9])
        self.page.write_text("<h1>Updated project</h1>")
        updated = await self.client.get("/A%20project/PROJECT.html", headers={"If-None-Match": etag})
        self.assertEqual(updated.status, 200)
        self.assertEqual(await updated.text(), "<h1>Updated project</h1>")

    async def test_write_methods_do_not_change_files(self):
        before = self.page.read_bytes()
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            response = await self.client.request(method, "/A%20project/PROJECT.html", data="overwrite")
            self.assertEqual(response.status, 405)
        self.assertEqual(self.page.read_bytes(), before)

    async def test_hidden_paths_and_encoded_traversal_are_not_served(self):
        (self.project / ".env").write_text("private fixture")
        (self.project / ".git").mkdir()
        (self.project / ".git/config").write_text("private fixture")
        (self.base / "outside.txt").write_text("outside fixture")
        for path in ("/A%20project/.env", "/A%20project/%2egit/config", "/%2e%2e/outside.txt", "/%2e%2e%2foutside.txt", "/%00"):
            response = await self.client.get(URL(path, encoded=True))
            self.assertEqual(response.status, 404, path)
            self.assertNotIn("fixture", await response.text())

    async def test_symlinks_stay_inside_root_and_cannot_reveal_hidden_files(self):
        (self.base / "outside.txt").write_text("outside fixture")
        (self.project / ".env").write_text("private fixture")
        (self.root / "inside.html").symlink_to(self.page)
        (self.root / "escape.txt").symlink_to(self.base / "outside.txt")
        (self.root / "escape-dir").symlink_to(self.base)
        (self.root / "alias.txt").symlink_to(self.project / ".env")
        self.assertEqual((await self.client.get("/inside.html")).status, 200)
        for path in ("/escape.txt", "/escape-dir/outside.txt", "/alias.txt"):
            self.assertEqual((await self.client.get(path)).status, 404)

    async def test_special_files_and_unchecked_compression_sidecars(self):
        os.mkfifo(self.root / "pipe.txt")
        self.assertEqual((await self.client.get("/pipe.txt")).status, 404)
        (self.base / "outside.gz").write_bytes(b"outside fixture")
        self.page.with_suffix(".html.gz").symlink_to(self.base / "outside.gz")
        response = await self.client.get("/A%20project/PROJECT.html", headers={"Accept-Encoding": "gzip, br"})
        self.assertEqual(response.status, 200)
        self.assertIn("Project π", await response.text())
        self.assertNotIn("Content-Encoding", response.headers)


if __name__ == "__main__":
    unittest.main()
