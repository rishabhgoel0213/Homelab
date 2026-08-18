#!/usr/bin/env python3

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(os.environ.get("BLOG_ADMIN_SCRIPT", "/srv/ops/scripts/blog-admin.py"))
ASSETS = Path(os.environ.get("BLOG_ADMIN_ASSETS", "/srv/ops/blog-admin"))
SPEC = importlib.util.spec_from_file_location("blog_admin", SCRIPT)
assert SPEC and SPEC.loader
blog_admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(blog_admin)


class BlogStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "blog"
        self.source.mkdir()
        (self.source / "_quarto.yml").write_text("project:\n  type: website\n", encoding="utf-8")
        self.store = blog_admin.BlogStore(
            self.source,
            "https://lab.example.test",
            "https://blog.example.test",
            "https://preview.example.test",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_slugify_and_validation(self) -> None:
        self.assertEqual(blog_admin.slugify("A Useful Notebook!"), "a-useful-notebook")
        self.assertEqual(blog_admin.ANSI_RE.sub("", "\x1b[34mbuild\x1b[0m"), "build")
        with self.assertRaises(ValueError):
            blog_admin.validate_slug("../escape")

    def test_admin_assets_use_cache_busted_urls(self) -> None:
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        self.assertIn('/admin/assets/app.js?v=project-imports-v2', html)
        self.assertIn('/admin/assets/styles.css?v=project-imports-v2', html)

    def test_create_and_update_document(self) -> None:
        post = self.store.create({"title": "First Post", "categories": ["notes"]})
        self.assertEqual(post["slug"], "first-post")
        self.assertTrue(post["draft"])
        self.assertEqual(post["kind"], "document")

        updated = self.store.update(
            "first-post",
            {
                "title": "First Post",
                "date": "2026-08-16",
                "categories": "notes, python",
                "draft": False,
            },
        )
        self.assertFalse(updated["draft"])
        self.assertEqual(updated["categories"], ["notes", "python"])

    def test_import_notebook(self) -> None:
        notebook = json.dumps(
            {
                "cells": [],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ).encode()
        post = self.store.create({"title": "Notebook"}, notebook)
        self.assertEqual(post["kind"], "notebook")
        self.assertIn("/lab/tree/", post["editorUrl"])
        self.assertEqual(post["postUrl"], "https://preview.example.test/posts/notebook/")

        published = self.store.update(
            "notebook",
            {"title": "Notebook", "date": "2026-08-16", "draft": False},
        )
        self.assertEqual(published["postUrl"], "https://blog.example.test/posts/notebook/")

    def test_rejects_duplicate_post(self) -> None:
        self.store.create({"title": "Duplicate"})
        with self.assertRaises(FileExistsError):
            self.store.create({"title": "Duplicate"})

    @staticmethod
    def write_notebook(path: Path, title: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "cells": [
                        {
                            "cell_type": "markdown",
                            "metadata": {},
                            "source": [f"# {title}\n"],
                        }
                    ],
                    "metadata": {},
                    "nbformat": 4,
                    "nbformat_minor": 5,
                }
            ),
            encoding="utf-8",
        )

    def test_project_import_links_all_notebooks_and_materializes_assets(self) -> None:
        project = self.root / "analysis-project"
        self.write_notebook(project / "overview.ipynb", "Overview")
        self.write_notebook(project / "notebooks" / "details.ipynb", "Detailed Results")
        self.write_notebook(project / ".ipynb_checkpoints" / "ignored.ipynb", "Ignored")
        (project / "images").mkdir()
        (project / "images" / "plot.png").write_bytes(b"png")
        payload = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "analysis-project",
            "title": "Analysis Project",
            "root": str(project),
            "managed": True,
            "environment": "nix",
        }

        with mock.patch.object(self.store.catalog, "list_projects", return_value=[payload]):
            imported = self.store.import_project(payload["id"])

        self.assertEqual(len(imported["posts"]), 2)
        self.assertTrue((self.source / ".blog-projects" / "analysis-project").is_symlink())
        posts = self.store.list_posts()
        self.assertEqual({post["title"] for post in posts}, {"Overview", "Detailed Results"})
        self.assertTrue(all(post["draft"] for post in posts))
        self.assertTrue(all(post["origin"] == "project" for post in posts))
        details = next(post for post in posts if post["title"] == "Detailed Results")
        self.assertEqual(
            details["postUrl"],
            "https://preview.example.test/posts/analysis-project/notebooks/details/",
        )

        updated = self.store.update(
            details["id"],
            {
                "title": "Published details",
                "date": "2026-08-18",
                "categories": ["research"],
                "draft": False,
            },
        )
        self.assertFalse(updated["draft"])
        self.assertEqual(
            updated["postUrl"],
            "https://blog.example.test/posts/analysis-project/notebooks/details/",
        )

        build_source = self.root / "build"
        shutil.copytree(self.source, build_source, symlinks=True)
        self.store.prepare_build_source(build_source)
        self.assertEqual(
            (
                build_source
                / "posts"
                / "analysis-project"
                / "_project"
                / "images"
                / "plot.png"
            ).read_bytes(),
            b"png",
        )
        staged = json.loads(
            (
                build_source
                / "posts"
                / "analysis-project"
                / "notebooks"
                / "details"
                / "index.ipynb"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(staged["metadata"]["title"], "Published details")
        self.assertFalse(staged["metadata"]["draft"])
        config = blog_admin.yaml.safe_load((build_source / "_quarto.yml").read_text(encoding="utf-8"))
        self.assertIn("posts/**/*.ipynb", config["project"]["render"])
        original = json.loads((project / "notebooks" / "details.ipynb").read_text(encoding="utf-8"))
        self.assertNotIn("title", original["metadata"])

    def test_delete_post_and_unlink_project_preserve_external_files(self) -> None:
        local = self.store.create({"title": "Delete me"})
        self.assertEqual(self.store.delete(local["id"])["removed"], "post")
        self.assertFalse((self.source / "posts" / "delete-me").exists())

        project = self.root / "linked-project"
        notebook = project / "linked.ipynb"
        self.write_notebook(notebook, "Linked")
        payload = {
            "id": "22222222-2222-4222-8222-222222222222",
            "name": "linked-project",
            "title": "Linked Project",
            "root": str(project),
            "managed": False,
            "environment": "host",
        }
        with mock.patch.object(self.store.catalog, "list_projects", return_value=[payload]):
            imported = self.store.import_project(payload["id"])
        removed = self.store.delete(imported["posts"][0]["id"])

        self.assertEqual(removed["removed"], "project")
        self.assertTrue(notebook.is_file())
        self.assertFalse((self.source / ".blog-projects" / "linked-project").exists())
        self.assertEqual(self.store.list_posts(), [])

    def test_prunes_only_draft_output(self) -> None:
        self.store.create({"title": "Draft post", "draft": True})
        self.store.create({"title": "Live post", "draft": False})
        output = self.source / "_site"
        (output / "posts" / "draft-post").mkdir(parents=True)
        (output / "posts" / "live-post").mkdir(parents=True)

        blog_admin.prune_draft_outputs(self.source, output)

        self.assertFalse((output / "posts" / "draft-post").exists())
        self.assertTrue((output / "posts" / "live-post").is_dir())

    def test_installs_resume(self) -> None:
        resume = self.source / "resume.pdf"
        output = self.source / "_site"
        output.mkdir()
        resume.write_bytes(b"resume")

        blog_admin.install_resume(resume, output)

        self.assertEqual((output / "rishabh-goel-resume.pdf").read_bytes(), b"resume")

    def test_publish_renders_internal_drafts_before_public_site(self) -> None:
        state = self.source / "public"
        preview_state = self.source / "preview"
        calls: list[list[str]] = []

        def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            calls.append(command)
            if command[0] == "quarto":
                output = Path(command[2]) / "_site"
                output.mkdir(exist_ok=True)
                (output / "index.html").write_text("site", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="")

        publisher = blog_admin.Publisher(
            self.source,
            state,
            "quarto",
            "rsync",
            preview_state=preview_state,
        )
        with mock.patch.object(blog_admin.subprocess, "run", side_effect=run):
            publisher.publish()

        build_source = Path(calls[0][2])
        output = build_source / "_site"
        self.assertNotEqual(build_source, self.source)
        self.assertEqual(calls[0][3:], ["--no-execute", "-M", "draft-mode:visible"])
        self.assertEqual(calls[1], ["rsync", "-a", "--delete", f"{output}/", f"{preview_state}/"])
        self.assertEqual(calls[2], ["quarto", "render", str(build_source), "--no-execute"])
        self.assertEqual(calls[3], ["rsync", "-a", "--delete", f"{output}/", f"{state}/"])

    def test_preview_only_renders_and_deploys_internal_site(self) -> None:
        state = self.source / "public"
        preview_state = self.source / "preview"
        calls: list[list[str]] = []

        def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            calls.append(command)
            if command[0] == "quarto":
                output = Path(command[2]) / "_site"
                output.mkdir(exist_ok=True)
                (output / "index.html").write_text("site", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="")

        publisher = blog_admin.Publisher(
            self.source,
            state,
            "quarto",
            "rsync",
            preview_state=preview_state,
        )
        with mock.patch.object(blog_admin.subprocess, "run", side_effect=run):
            result = publisher.preview()

        self.assertEqual(result["state"], "previewed")
        build_source = Path(calls[0][2])
        output = build_source / "_site"
        self.assertNotEqual(build_source, self.source)
        self.assertEqual(calls[0][3:], ["--no-execute", "-M", "draft-mode:visible"])
        self.assertEqual(calls[1], ["rsync", "-a", "--delete", f"{output}/", f"{preview_state}/"])


if __name__ == "__main__":
    unittest.main()
