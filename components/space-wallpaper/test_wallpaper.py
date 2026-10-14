import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(os.environ.get("SPACE_WALLPAPER_ROOT", Path(__file__).parent))
spec = importlib.util.spec_from_file_location("wallpaper", ROOT / "wallpaper.py")
wallpaper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wallpaper)


class Response(io.BytesIO):
    url = "https://images-assets.nasa.gov/image/test.jpg"

    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}


class Wallpapers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "pictures"
        self.images.mkdir()
        self.state_path = self.root / "state.json"
        self.cfg = dict(directory=str(self.images), intervalSeconds=3600, cacheImages=2,
                        maxDownloadMiB=2, maxImageMiB=1)
        self.entries = [dict(id=str(i), title=f"Image {i}", description="A real image of space.",
                             width=4000, height=2400,
                             url=f"https://images-assets.nasa.gov/image/{i}.jpg",
                             source=f"https://images.nasa.gov/details/{i}") for i in range(4)]

    def fake_download(self, entry, directory, cfg):
        path = wallpaper.image_path(directory, entry["id"])
        path.write_bytes(b"fixture")
        return path

    def test_curated_catalogue_and_url_validation(self):
        entries = wallpaper.validate_catalogue(json.loads((ROOT / "catalogue.json").read_text()))
        self.assertGreaterEqual(len(entries), 20)
        for change in [dict(id="../escape"), dict(url="http://images.nasa.gov/image.jpg"),
                       dict(url="https://example.com/image.jpg"), dict(width=1200)]:
            altered = [{**self.entries[0], **change}, self.entries[1]]
            with self.assertRaises(ValueError):
                wallpaper.validate_catalogue(altered)

    def test_decode_and_cache_valid_image_without_refetch(self):
        data = io.BytesIO()
        Image.new("RGB", (6000, 3600), "navy").save(data, "JPEG")
        with patch.object(wallpaper.urllib.request, "urlopen", return_value=Response(data.getvalue())) as fetch:
            path = wallpaper.download_image(self.entries[0], self.images, self.cfg)
            self.assertEqual(path, wallpaper.download_image(self.entries[0], self.images, self.cfg))
            self.assertEqual(fetch.call_count, 1)
        with Image.open(path) as image:
            self.assertEqual(image.size, (5120, 3072))
        self.assertEqual(list(self.images.glob(".space-*")), [])

    def test_bad_downloads_do_not_publish_or_leave_temporary_files(self):
        small = io.BytesIO()
        Image.new("RGB", (200, 200)).save(small, "PNG")
        responses = [Response(b"not an image"), Response(small.getvalue()),
                     Response(b"oversize", length=10_000_000), Response(b"x" * (2 * wallpaper.MIB + 1), length=0)]
        for response in responses:
            with patch.object(wallpaper.urllib.request, "urlopen", return_value=response):
                with self.assertRaises((OSError, ValueError)):
                    wallpaper.download_image(self.entries[0], self.images, self.cfg)
            self.assertEqual(list(self.images.iterdir()), [])

    def test_shuffle_no_repeats_cache_bound_and_user_files_preserved(self):
        user_file = self.images / "space-my-photo.jpg"
        user_file.write_bytes(b"user picture")
        state, seen = {}, []
        with patch.object(wallpaper, "download_image", side_effect=self.fake_download):
            for _ in range(len(self.entries)):
                wallpaper.rotate(self.cfg, self.entries, state, self.state_path, True, lambda p: None)
                seen.append(state["current"]["id"])
                managed = [p for p in self.images.glob("space-*.jpg") if p != user_file]
                self.assertLessEqual(len(managed), 2)
                self.assertTrue(Path(state["current"]["file"]).exists())
        self.assertEqual(len(set(seen)), len(self.entries))
        self.assertEqual(user_file.read_bytes(), b"user picture")

    def test_offline_uses_cache_and_keeps_current_if_none_available(self):
        current = self.fake_download(self.entries[0], self.images, self.cfg)
        alternate = self.fake_download(self.entries[1], self.images, self.cfg)
        state = dict(current={**self.entries[0], "file": str(current)})
        with patch.object(wallpaper, "download_image", side_effect=OSError("offline")):
            with patch("sys.stderr", new=io.StringIO()):
                wallpaper.rotate(self.cfg, self.entries, state, self.state_path, True, lambda p: None)
        self.assertEqual(state["current"]["id"], "1")
        self.assertEqual(Path(state["current"]["file"]), alternate)
        current.unlink()
        original = self.state_path.read_text()
        with patch.object(wallpaper, "download_image", side_effect=OSError("offline")):
            with patch("sys.stderr", new=io.StringIO()), self.assertRaises(RuntimeError):
                wallpaper.rotate(self.cfg, self.entries, state, self.state_path, True, lambda p: None)
        self.assertEqual(self.state_path.read_text(), original)
        self.assertTrue(alternate.exists())

    def test_macos_failure_keeps_state_and_previous_cached_image(self):
        path = self.fake_download(self.entries[0], self.images, self.cfg)
        state = dict(current={**self.entries[0], "file": str(path)}, remaining=["1"])
        wallpaper.atomic_json(self.state_path, state)
        original = self.state_path.read_text()
        with patch.object(wallpaper, "download_image", side_effect=self.fake_download):
            with self.assertRaises(RuntimeError):
                wallpaper.rotate(self.cfg, self.entries, state, self.state_path, True,
                                 lambda p: (_ for _ in ()).throw(RuntimeError("display failure")))
        self.assertEqual(self.state_path.read_text(), original)
        self.assertTrue(path.exists())

    def test_pause_and_interval_prevent_downloads(self):
        for state in [dict(paused=True), dict(changedAt=wallpaper.time.time())]:
            with patch.object(wallpaper, "download_image") as download:
                self.assertFalse(wallpaper.rotate(self.cfg, self.entries, state, self.state_path))
                download.assert_not_called()

    def test_menu_metadata_cannot_inject_swiftbar_commands(self):
        state = dict(current={**self.entries[0], "title": "Hello\nInjected | bash=evil"})
        with patch("sys.stdout", new=io.StringIO()) as output:
            wallpaper.menu(state, self.cfg)
        self.assertIn("Hello Injected   bash=evil | length=80", output.getvalue())
        self.assertNotIn("\nInjected", output.getvalue())


if __name__ == "__main__":
    unittest.main()
