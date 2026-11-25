#!/usr/bin/env python3
"""Offline unit and integration tests for components/skills/bin/skills.py."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


def load_skills_module():
    script = Path(
        os.environ.get(
            "SKILLS_SCRIPT",
            str(Path(__file__).resolve().parent.parent / "bin" / "skills.py"),
        )
    )
    spec = importlib.util.spec_from_file_location("homelab_skills", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SKILLS = load_skills_module()


def write_skill(
    directory: Path,
    name: str,
    description: str = "A helpful test skill.",
    body: str = "# Test Skill\n\nFollow these steps.\n",
    extra_files: dict[str, str] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    content = f'---\nname: "{name}"\ndescription: "{description}"\n---\n\n{body}'
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    for rel, text in (extra_files or {}).items():
        target = directory / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return directory


def git_run(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


class SkillsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="skills-test-")
        self.root = Path(self._tmp.name)
        self.state_dir = self.root / "state"
        self.decl_dir = self.root / "declarative"
        self.decl_meta = self.root / "declarative-meta.json"
        self.codex_dir = self.root / "codex-skills"
        self.claude_dir = self.root / "claude-skills"
        self.agy_dir = self.root / "agy-skills"
        self.extra_dir = self.root / "agents-skills"
        self.t3_agy_dir = self.root / "t3-agy"

        # Seed harness-owned directories that must never be touched
        (self.codex_dir / ".system" / "builtin").mkdir(parents=True)
        (self.codex_dir / ".system" / "builtin" / "SKILL.md").write_text("system", encoding="utf-8")
        (self.claude_dir / "synced" / "bucket").mkdir(parents=True)
        (self.claude_dir / "synced" / "bucket" / "note.txt").write_text("cloud", encoding="utf-8")

        self.decl_dir.mkdir(parents=True)
        self.decl_meta.write_text("{}\n", encoding="utf-8")

        self._old_env = dict(os.environ)
        os.environ["SKILLS_STATE"] = str(self.state_dir)
        os.environ["SKILLS_DECLARATIVE_DIR"] = str(self.decl_dir)
        os.environ["SKILLS_DECLARATIVE_META"] = str(self.decl_meta)
        os.environ["SKILLS_TARGETS"] = (
            f"codex={self.codex_dir}:claude={self.claude_dir}:antigravity={self.agy_dir}"
        )
        os.environ["SKILLS_EXTRA_SCAN_DIRS"] = str(self.extra_dir)
        os.environ["SKILLS_T3_ANTIGRAVITY_ROOT"] = str(self.t3_agy_dir)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)
        # Ensure any read-only test fixtures can be removed cleanly
        for dirpath, dirnames, filenames in os.walk(self.root):
            os.chmod(dirpath, 0o755)
            for fname in filenames:
                os.chmod(Path(dirpath) / fname, 0o644)
        self._tmp.cleanup()

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = SKILLS.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_frontmatter_parsing_variants(self) -> None:
        # Folded block scalar + single quotes + comment
        skill_dir = self.root / "fm-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: 'fm-skill'\n"
            "description: >-\n"
            "  First line of description\n"
            "  second line here.\n"
            "extra: ignored # inline comment\n"
            "---\n\nBody\n",
            encoding="utf-8",
        )
        meta = SKILLS.validate_skill_dir(skill_dir, expected_name="fm-skill")
        self.assertEqual(meta.name, "fm-skill")
        self.assertEqual(meta.description, "First line of description second line here.")

        # Missing frontmatter fails
        bad_dir = self.root / "bad-skill"
        bad_dir.mkdir()
        (bad_dir / "SKILL.md").write_text("# No frontmatter\n", encoding="utf-8")
        with self.assertRaises(SKILLS.SkillError):
            SKILLS.validate_skill_dir(bad_dir)

        # Invalid name fails
        bad_name = self.root / "bad-name"
        bad_name.mkdir()
        (bad_name / "SKILL.md").write_text(
            "---\nname: ../escape\ndescription: nope\n---\n", encoding="utf-8"
        )
        with self.assertRaises(SKILLS.SkillError):
            SKILLS.validate_skill_dir(bad_name)

    def test_parse_source_formats(self) -> None:
        p1 = SKILLS.parse_source("github:janestreet/agent_skills/socratic-tutor")
        self.assertEqual(p1.kind, "git")
        self.assertEqual(p1.owner, "janestreet")
        self.assertEqual(p1.repo, "agent_skills")
        self.assertEqual(p1.subpath, "socratic-tutor")
        self.assertEqual(p1.url, "https://github.com/janestreet/agent_skills.git")

        p2 = SKILLS.parse_source(
            "https://github.com/janestreet/agent_skills/blob/master/socratic-tutor/SKILL.md"
        )
        self.assertEqual(p2.owner, "janestreet")
        self.assertEqual(p2.repo, "agent_skills")
        self.assertEqual(p2.ref, "master")
        self.assertEqual(p2.subpath, "socratic-tutor")

        p3 = SKILLS.parse_source("owner/repo/skills/foo")
        self.assertEqual(p3.owner, "owner")
        self.assertEqual(p3.repo, "repo")
        self.assertEqual(p3.subpath, "skills/foo")

    def test_declarative_sync_readonly_and_cleanup(self) -> None:
        s_dir = write_skill(
            self.decl_dir / "socratic-tutor",
            "socratic-tutor",
            "Socratic tutoring.",
            extra_files={"scripts/helper.sh": "#!/bin/sh\necho hi\n"},
        )
        os.chmod(s_dir / "scripts" / "helper.sh", 0o555)
        os.chmod(s_dir / "SKILL.md", 0o444)
        os.chmod(s_dir / "scripts", 0o555)
        os.chmod(s_dir, 0o555)
        self.decl_meta.write_text(
            json.dumps(
                {
                    "socratic-tutor": {
                        "source": "github:janestreet/agent_skills/socratic-tutor",
                        "rev": "469868f4489cbdbe178c775a0af05bb6bef63689",
                    }
                }
            ),
            encoding="utf-8",
        )

        code, out, err = self.run_cli("sync")
        self.assertEqual(code, 0, err)
        for target in (self.codex_dir, self.claude_dir, self.agy_dir):
            self.assertTrue((target / "socratic-tutor" / "SKILL.md").is_file())
            mode = (target / "socratic-tutor" / "scripts" / "helper.sh").stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR)

        # Harness-owned dirs untouched
        self.assertTrue((self.codex_dir / ".system" / "builtin" / "SKILL.md").is_file())
        self.assertTrue((self.claude_dir / "synced" / "bucket" / "note.txt").is_file())

        # Doctor passes
        code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 0, err)
        self.assertIn("Doctor check passed.", out)

        # Removing from declarative prunes all 3 targets cleanly
        os.chmod(s_dir, 0o755)
        os.chmod(s_dir / "scripts", 0o755)
        os.chmod(s_dir / "scripts" / "helper.sh", 0o644)
        os.chmod(s_dir / "SKILL.md", 0o644)
        import shutil

        shutil.rmtree(s_dir)

        code, out, err = self.run_cli("sync")
        self.assertEqual(code, 0, err)
        for target in (self.codex_dir, self.claude_dir, self.agy_dir):
            self.assertFalse((target / "socratic-tutor").exists())
        self.assertTrue((self.codex_dir / ".system" / "builtin" / "SKILL.md").is_file())
        self.assertTrue((self.claude_dir / "synced" / "bucket" / "note.txt").is_file())

    def test_hybrid_override_and_restore(self) -> None:
        write_skill(self.decl_dir / "demo", "demo", "Declarative v1", body="v1\n")
        self.assertEqual(self.run_cli("sync")[0], 0)

        local_override = write_skill(
            self.root / "local-demo", "demo", "Local override v2", body="v2\n"
        )
        code, out, err = self.run_cli("add", str(local_override))
        self.assertEqual(code, 0, err)
        self.assertIn("overrides declarative", out)

        # All harnesses now see v2
        for target in (self.codex_dir, self.claude_dir, self.agy_dir):
            self.assertIn("v2", (target / "demo" / "SKILL.md").read_text(encoding="utf-8"))

        # JSON list shows override
        code, out, _ = self.run_cli("list", "--json")
        self.assertEqual(code, 0)
        items = json.loads(out)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["origin"], "installed")
        self.assertTrue(items[0]["overridesDeclarative"])

        # Removing mutable override restores declarative v1
        code, out, err = self.run_cli("remove", "demo")
        self.assertEqual(code, 0, err)
        self.assertIn("restored declarative version", out)
        for target in (self.codex_dir, self.claude_dir, self.agy_dir):
            self.assertIn("v1", (target / "demo" / "SKILL.md").read_text(encoding="utf-8"))

        # Removing declarative-only skill fails cleanly with guidance
        code, _, err = self.run_cli("remove", "demo")
        self.assertNotEqual(code, 0)
        self.assertIn("declarative.nix", err)

    def test_git_add_update_and_promote(self) -> None:
        repo = self.root / "upstream-repo"
        repo.mkdir()
        git_run(repo, "init", "-b", "main")
        write_skill(repo / "skills" / "alpha", "alpha", "Alpha v1", body="alpha-v1\n")
        write_skill(repo / "skills" / "beta", "beta", "Beta v1", body="beta-v1\n")
        git_run(repo, "add", ".")
        git_run(repo, "commit", "-m", "initial")
        rev1 = git_run(repo, "rev-parse", "HEAD")

        repo_url = repo.as_uri()
        # Multi-skill repo without --skill or --all should error listing choices
        code, _, err = self.run_cli("add", repo_url)
        self.assertNotEqual(code, 0)
        self.assertIn("alpha", err)
        self.assertIn("beta", err)

        # Install single skill by name
        code, out, err = self.run_cli("add", repo_url, "--skill", "alpha")
        self.assertEqual(code, 0, err)
        self.assertIn(rev1[:10], out)

        manifest = json.loads((self.state_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"]["alpha"]["rev"], rev1)
        self.assertEqual(manifest["skills"]["alpha"]["subpath"], "skills/alpha")

        # Update upstream repo and run `skills update`
        write_skill(repo / "skills" / "alpha", "alpha", "Alpha v2", body="alpha-v2\n")
        git_run(repo, "add", ".")
        git_run(repo, "commit", "-m", "bump alpha")
        rev2 = git_run(repo, "rev-parse", "HEAD")

        code, out, err = self.run_cli("update", "alpha")
        self.assertEqual(code, 0, err)
        self.assertIn(rev2[:10], out)
        for target in (self.codex_dir, self.claude_dir, self.agy_dir):
            self.assertIn("alpha-v2", (target / "alpha" / "SKILL.md").read_text(encoding="utf-8"))

        # Simulate GitHub metadata to test promote / export-nix
        manifest = json.loads((self.state_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["skills"]["alpha"]["owner"] = "example"
        manifest["skills"]["alpha"]["repo"] = "skills-repo"
        (self.state_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        code, out, err = self.run_cli("promote", "alpha", "--no-prefetch")
        self.assertEqual(code, 0, err)
        self.assertIn('owner = "example";', out)
        self.assertIn('repo = "skills-repo";', out)
        self.assertIn(f'rev = "{rev2}";', out)
        self.assertIn("lib.fakeHash", out)

    def test_unmanaged_conflict_is_never_clobbered(self) -> None:
        # Drop an unmanaged directory in claude's skills folder
        unmanaged = self.claude_dir / "custom"
        unmanaged.mkdir(parents=True)
        (unmanaged / "SKILL.md").write_text("user manual copy", encoding="utf-8")

        write_skill(self.decl_dir / "custom", "custom", "Managed copy", body="managed\n")
        code, out, _ = self.run_cli("sync")
        self.assertEqual(code, 1)
        self.assertIn("conflict", out)
        # Unmanaged copy preserved verbatim
        self.assertEqual((unmanaged / "SKILL.md").read_text(encoding="utf-8"), "user manual copy")
        # Other harnesses still synced cleanly
        self.assertIn("managed", (self.codex_dir / "custom" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("managed", (self.agy_dir / "custom" / "SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
