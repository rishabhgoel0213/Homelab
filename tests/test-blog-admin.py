#!/usr/bin/env python3

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(os.environ.get("BLOG_ADMIN_SCRIPT", "/srv/ops/scripts/blog-admin.py"))
SPEC = importlib.util.spec_from_file_location("blog_admin", SCRIPT)
assert SPEC and SPEC.loader
blog_admin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(blog_admin)


class BlogStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.source = Path(self.temporary.name)
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
        output = self.source / "_site"
        calls: list[list[str]] = []

        def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            calls.append(command)
            if command[0] == "quarto":
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

        self.assertEqual(
            calls,
            [
                ["quarto", "render", str(self.source), "-M", "draft-mode:visible"],
                ["rsync", "-a", "--delete", f"{output}/", f"{preview_state}/"],
                ["quarto", "render", str(self.source)],
                ["rsync", "-a", "--delete", f"{output}/", f"{state}/"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
