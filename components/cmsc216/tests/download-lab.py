"""Offline tests for lab discovery and safe archive publication."""

import importlib.util
import io
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "download_lab", Path(__file__).resolve().parents[1] / "bin/download-lab.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Downloads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("lab02-code/QUESTIONS.txt", "starter")
        self.zip = data.getvalue()
        self.pages = {
            "schedule.html": b'<a href="lab02.html">Lab02</a><a href="lab01.html">Lab01</a>',
            "lab01.html": b'<a href="lab01-code.zip">Code</a>',
            "lab02.html": b'<a href="lab02-code.zip">Code</a>',
            "lab01-code.zip": self.zip,
            "lab02-code.zip": self.zip,
        }
        self.mock = patch.object(module.urllib.request, "urlopen", side_effect=self.fetch)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def fetch(self, url, timeout):
        self.assertEqual(timeout, 30)
        return io.BytesIO(self.pages[url.removeprefix(module.BASE)])

    def test_existing_folder_and_repeat(self):
        (self.root / "lab1-code").mkdir()
        module.download(self.root)
        self.assertEqual((self.root / "lab02-code.zip").read_bytes(), self.zip)
        module.download(self.root)
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_numeric_order_and_direct_archive(self):
        self.pages["schedule.html"] = b'<a href="lab10.html">10</a><a href="lab02-code.zip">2</a>'
        module.download(self.root)
        self.assertTrue((self.root / "lab02-code.zip").exists())

    def test_empty_workspace_starts_at_one(self):
        module.download(self.root)
        self.assertTrue((self.root / "lab01-code.zip").exists())

    def test_invalid_zip_leaves_no_partial_file(self):
        (self.root / "lab01-code.zip").write_bytes(b"existing work")
        self.pages["lab02-code.zip"] = b"<html>Error</html>"
        with self.assertRaises(zipfile.BadZipFile):
            module.download(self.root)
        self.assertEqual(list(self.root.iterdir()), [self.root / "lab01-code.zip"])
        self.assertEqual((self.root / "lab01-code.zip").read_bytes(), b"existing work")

    def test_missing_archive(self):
        self.pages["lab01.html"] = b"Not released yet"
        with self.assertRaisesRegex(ValueError, "no published code ZIP"):
            module.download(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_network_failure(self):
        with patch.object(module.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(urllib.error.URLError):
                module.download(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_concurrent_destination_is_preserved(self):
        original_link = module.os.link

        def competing_download(source, destination):
            destination.write_bytes(b"other download")
            original_link(source, destination)

        with patch.object(module.os, "link", side_effect=competing_download):
            with self.assertRaises(FileExistsError):
                module.download(self.root)
        self.assertEqual((self.root / "lab01-code.zip").read_bytes(), b"other download")
        self.assertEqual(len(list(self.root.iterdir())), 1)


class ProjectDownloads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("p1-code/QUESTIONS.txt", "starter")
        self.zip = data.getvalue()
        self.pages = {
            "schedule.html": b'<a href="p2.html">P2</a><a href="p1.html">Project 1</a>',
            "p1.html": b'<a href="p1-code.zip">Code</a>',
            "p2.html": b'<a href="p2-code.zip">Code</a>',
            "p1-code.zip": self.zip,
            "p2-code.zip": self.zip,
        }
        self.mock = patch.object(module.urllib.request, "urlopen", side_effect=self.fetch)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def fetch(self, url, timeout):
        self.assertEqual(timeout, 30)
        return io.BytesIO(self.pages[url.removeprefix(module.BASE)])

    def test_empty_workspace_starts_at_one(self):
        module.download(self.root, "project")
        self.assertEqual((self.root / "p1-code.zip").read_bytes(), self.zip)

    def test_existing_folder_and_repeat(self):
        (self.root / "p1-code").mkdir()
        module.download(self.root, "project")
        self.assertEqual((self.root / "p2-code.zip").read_bytes(), self.zip)
        module.download(self.root, "project")
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_numeric_order_and_direct_archive(self):
        self.pages["schedule.html"] = b'<a href="p10.html">10</a><a href="p2-code.zip">2</a>'
        module.download(self.root, "project")
        self.assertTrue((self.root / "p2-code.zip").exists())

    def test_missing_archive(self):
        self.pages["p1.html"] = b"Not released yet"
        with self.assertRaisesRegex(ValueError, "Project 1 has no published code ZIP"):
            module.download(self.root, "project")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_zip_leaves_no_partial_file(self):
        self.pages["p1-code.zip"] = b"<html>Error</html>"
        with self.assertRaises(zipfile.BadZipFile):
            module.download(self.root, "project")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unsupported_kind(self):
        with self.assertRaisesRegex(ValueError, "Unsupported coursework kind"):
            module.download(self.root, "quiz")


if __name__ == "__main__":
    unittest.main()
