#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(
    os.environ.get(
        "PROJECTCTL_SCRIPT", Path(__file__).parent.parent / "scripts" / "projectctl.py"
    )
)


class ProjectCtlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.projects = self.root / "Projects"
        self.projects.mkdir()
        self.kernels = self.root / "kernels"
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PROJECTS_ROOT": str(self.projects),
                "PROJECTCTL_JUPYTER_URL": "https://lab.example.test",
                "PROJECTCTL_JUPYTER_ROOT": "/",
                "PROJECTCTL_JUPYTER_KERNEL_DIR": str(self.kernels),
                "PROJECTCTL_SELF": "/run/current-system/sw/bin/projectctl",
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_projectctl(
        self, *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=check,
            capture_output=True,
            text=True,
            env=self.environment,
        )

    def create_project(self, name: str = "Linear Algebra") -> Path:
        result = self.run_projectctl("create", name, "--json")
        return Path(json.loads(result.stdout)["root"])

    def test_create_scaffolds_manifest_environment_and_content_layout(self) -> None:
        project = self.create_project()
        self.assertEqual(project, self.projects / "linear-algebra")
        for relative in (
            "project.toml",
            "flake.nix",
            "AGENTS.md",
            "sources/original",
            "sources/processed",
            "notebooks",
            "notes",
            "src",
            "figures",
            "artifacts",
        ):
            self.assertTrue((project / relative).exists(), relative)

        listing = json.loads(self.run_projectctl("list", "--json").stdout)
        self.assertEqual(1, len(listing["projects"]))
        self.assertTrue(listing["projects"][0]["managed"])
        self.assertEqual("nix", listing["projects"][0]["environment"])

    def test_existing_directories_are_usable_and_can_be_initialized_without_overwrite(
        self,
    ) -> None:
        (self.projects / "templates").mkdir()
        existing = self.projects / "existing-research"
        existing.mkdir()
        original_flake = "{ outputs = _: {}; }\n"
        (existing / "flake.nix").write_text(original_flake, encoding="utf-8")

        listing = json.loads(self.run_projectctl("list", "--json").stdout)
        self.assertEqual(1, len(listing["projects"]))
        self.assertFalse(listing["projects"][0]["managed"])
        implicit_id = listing["projects"][0]["id"]
        self.run_projectctl("init", "existing-research", "--title", "Existing Research")
        self.assertEqual(
            original_flake, (existing / "flake.nix").read_text(encoding="utf-8")
        )
        shown = json.loads(
            self.run_projectctl("show", "existing-research", "--json").stdout
        )
        self.assertTrue(shown["managed"])
        self.assertEqual(implicit_id, shown["id"])
        self.assertEqual("Existing Research", shown["title"])
        jupyter = json.loads(
            self.run_projectctl("jupyter", "existing-research", "--json").stdout
        )
        self.assertIsNone(jupyter["kernel"])
        self.assertFalse(self.kernels.exists())

    def test_capabilities_and_reversible_project_lifecycle(self) -> None:
        self.create_project("Lifecycle")
        capabilities = json.loads(self.run_projectctl("capabilities", "--json").stdout)
        self.assertEqual(1, capabilities["api_version"])
        self.assertIn("unarchive", capabilities["operations"])

        archived = json.loads(
            self.run_projectctl("archive", "lifecycle", "--json").stdout
        )
        self.assertEqual("archived", archived["status"])
        self.assertEqual(
            [], json.loads(self.run_projectctl("list", "--json").stdout)["projects"]
        )

        renamed = json.loads(
            self.run_projectctl("rename", "lifecycle", "Life Cycle", "--json").stdout
        )
        self.assertEqual("Life Cycle", renamed["title"])
        active = json.loads(
            self.run_projectctl("unarchive", "lifecycle", "--json").stdout
        )
        self.assertEqual("active", active["status"])

    def test_jupyter_registers_project_kernel_and_prints_deep_link(self) -> None:
        project = self.create_project("Course Notes")
        result = json.loads(
            self.run_projectctl("jupyter", "course-notes", "--json").stdout
        )
        self.assertEqual(
            f"https://lab.example.test/lab/tree/{project.as_posix().lstrip('/')}",
            result["url"],
        )
        kernel = json.loads(
            (self.kernels / result["kernel"] / "kernel.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("/run/current-system/sw/bin/projectctl", kernel["argv"][0])
        self.assertEqual("kernel", kernel["argv"][1])
        self.assertIn("Python (Course Notes)", kernel["display_name"])

    def test_session_launch_is_harness_agnostic_and_uses_project_cwd(self) -> None:
        self.create_project("Session Test")
        harness = self.root / "fake-harness"
        harness.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "print(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n",
            encoding="utf-8",
        )
        harness.chmod(0o755)
        self.environment["PROJECTCTL_HARNESSES_JSON"] = json.dumps(
            {"future-agent": [str(harness)]}
        )

        result = self.run_projectctl(
            "session",
            "--direct",
            "session-test",
            "future-agent",
            "--",
            "hello",
        )
        payload = json.loads(result.stdout)
        self.assertEqual(str(self.projects / "session-test"), payload["cwd"])
        self.assertEqual(["hello"], payload["args"])

        nested = self.projects / "session-test" / "src"
        nested_result = self.run_projectctl(
            "exec",
            "--direct",
            "--cwd",
            str(nested),
            "session-test",
            "--",
            str(harness),
        )
        self.assertEqual(str(nested), json.loads(nested_result.stdout)["cwd"])

    def test_clean_stdout_keeps_environment_output_off_command_stdout(self) -> None:
        self.create_project("Protocol Provider")
        fake_nix = self.root / "fake-nix"
        fake_nix.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "print('environment banner', flush=True)\n"
            "command_index = sys.argv.index('--command') + 1\n"
            "command = sys.argv[command_index:]\n"
            "os.execvpe(command[0], command, os.environ.copy())\n",
            encoding="utf-8",
        )
        fake_nix.chmod(0o755)
        controller = self.root / "projectctl-self"
        controller.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            f"script = {str(SCRIPT)!r}\n"
            "os.execv(sys.executable, [sys.executable, script, *sys.argv[1:]])\n",
            encoding="utf-8",
        )
        controller.chmod(0o755)
        provider = self.root / "fake-provider"
        provider.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "print(json.dumps({'provider': 'stdout'}))\n"
            "print('provider stderr', file=sys.stderr)\n",
            encoding="utf-8",
        )
        provider.chmod(0o755)
        self.environment.update(
            {
                "PROJECTCTL_NIX_BIN": str(fake_nix),
                "PROJECTCTL_SELF": str(controller),
            }
        )

        result = self.run_projectctl(
            "exec",
            "--clean-stdout",
            "protocol-provider",
            "--",
            str(provider),
        )

        self.assertEqual({"provider": "stdout"}, json.loads(result.stdout))
        self.assertIn("environment banner", result.stderr)
        self.assertIn("provider stderr", result.stderr)

    def test_rejects_projects_outside_canonical_root(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        result = self.run_projectctl("show", str(outside), check=False)
        self.assertEqual(2, result.returncode)
        self.assertIn("must be under", result.stderr)


if __name__ == "__main__":
    unittest.main()
