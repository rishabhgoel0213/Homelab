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
        self.syncthing_state = self.root / "syncthing.json"
        self.syncthing_state.write_text('{"folders": {}}\n', encoding="utf-8")
        self.syncthing_cli = self.root / "fake-syncthing.py"
        self.syncthing_cli.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            "state_path = Path(sys.argv[1])\n"
            "args = sys.argv[2:]\n"
            "state = json.loads(state_path.read_text())\n"
            "folders = state['folders']\n"
            "default = {\n"
            "  'id': '', 'label': '', 'path': '', 'type': 'sendreceive',\n"
            "  'devices': [], 'fsWatcherEnabled': True, 'rescanIntervalS': 3600,\n"
            "  'versioning': {'type': '', 'params': {}, 'cleanupIntervalS': 3600, 'fsPath': '', 'fsType': 'basic'}\n"
            "}\n"
            "if args == ['show', 'system']:\n"
            "    print(json.dumps({'myID': 'LOCAL-DEVICE'}))\n"
            "elif args == ['config', 'folders', 'list']:\n"
            "    print('\\n'.join(sorted(folders)))\n"
            "elif args == ['config', 'defaults', 'folder', 'dump-json']:\n"
            "    print(json.dumps(default))\n"
            "elif len(args) == 4 and args[:2] == ['config', 'folders'] and args[3] == 'dump-json':\n"
            "    print(json.dumps(folders[args[2]]))\n"
            "elif len(args) == 4 and args[:3] == ['config', 'folders', 'add-json']:\n"
            "    folder = json.loads(args[3]); folders[folder['id']] = folder\n"
            "    state_path.write_text(json.dumps(state))\n"
            "elif len(args) == 4 and args[:2] == ['config', 'folders'] and args[3] == 'delete':\n"
            "    folders.pop(args[2], None); state_path.write_text(json.dumps(state))\n"
            "else:\n"
            "    print('unsupported fake Syncthing arguments: ' + repr(args), file=sys.stderr); sys.exit(2)\n",
            encoding="utf-8",
        )
        self.syncthing_cli.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PROJECTS_ROOT": str(self.projects),
                "PROJECTCTL_JUPYTER_URL": "https://lab.example.test",
                "PROJECTCTL_JUPYTER_ROOT": "/",
                "PROJECTCTL_JUPYTER_KERNEL_DIR": str(self.kernels),
                "PROJECTCTL_SELF": "/run/current-system/sw/bin/projectctl",
                "PROJECTCTL_IDE_BIN": str(self.root / "fake-vscodium-env"),
                "PROJECTCTL_SYNC_ROLE": "server",
                "PROJECTCTL_SYNC_PEERS_JSON": json.dumps(
                    {
                        "macbook": {
                            "device_id": "MAC-DEVICE",
                            "projects_root": "/Users/test/Projects",
                            "ssh_host": "test@macbook",
                            "remote_projectctl": "/run/current-system/sw/bin/projectctl",
                        }
                    }
                ),
                "PROJECTCTL_SYNCTHING_COMMAND_JSON": json.dumps(
                    [sys.executable, str(self.syncthing_cli), str(self.syncthing_state)]
                ),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_projectctl(
        self, *arguments: str, check: bool = True, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=check,
            capture_output=True,
            text=True,
            env=self.environment,
            input=input_text,
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
        self.assertEqual("general", listing["projects"][0]["editor_preset"])
        self.assertIn("aarch64-darwin", (project / "flake.nix").read_text())

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
        self.assertIn("sync.deploy", capabilities["operations"])
        self.assertIn("ide", capabilities["operations"])

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

    def test_ide_uses_manifest_preset_override_and_validated_cwd(self) -> None:
        project = self.create_project("IDE Test")
        manifest = project / "project.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                'preset = "general"', 'preset = "research"'
            ),
            encoding="utf-8",
        )
        ide = Path(self.environment["PROJECTCTL_IDE_BIN"])
        ide.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "print(json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        ide.chmod(0o755)

        nested = project / "src"
        result = self.run_projectctl("ide", "ide-test", "--cwd", "src")
        self.assertEqual(
            ["open", "research", str(nested)], json.loads(result.stdout)
        )

        overridden = self.run_projectctl(
            "ide", "ide-test", "--preset", "general"
        )
        self.assertEqual(
            ["open", "general", str(project)], json.loads(overridden.stdout)
        )

        outside = self.root / "outside-ide"
        outside.mkdir()
        rejected = self.run_projectctl(
            "ide", "ide-test", "--cwd", str(outside), check=False
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("must remain under project root", rejected.stderr)

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

    def test_project_sync_is_declarative_and_reconcile_preserves_files(self) -> None:
        project = self.create_project("Sync Me")
        enabled = json.loads(
            self.run_projectctl(
                "sync", "enable", "sync-me", "--target", "macbook", "--json"
            ).stdout
        )
        self.assertEqual(["macbook"], enabled["project"]["sync_targets"])
        self.assertEqual({}, json.loads(self.syncthing_state.read_text())["folders"])

        reconciled = json.loads(
            self.run_projectctl("sync", "reconcile", "--json").stdout
        )
        folder_id = f"project-{enabled['project']['id']}"
        self.assertEqual([folder_id], reconciled["created_or_updated"])
        folder = json.loads(self.syncthing_state.read_text())["folders"][folder_id]
        self.assertEqual(str(project), folder["path"])
        self.assertEqual("staggered", folder["versioning"]["type"])
        self.assertEqual(
            ["LOCAL-DEVICE", "MAC-DEVICE"],
            [device["deviceID"] for device in folder["devices"]],
        )
        self.assertIn("(?d).git", (project / ".stignore").read_text())

        sentinel = project / "keep-me.txt"
        sentinel.write_text("preserved\n", encoding="utf-8")
        disabled = json.loads(
            self.run_projectctl(
                "sync", "disable", "sync-me", "--target", "macbook", "--json"
            ).stdout
        )
        self.assertTrue(disabled["files_preserved"])
        self.run_projectctl("sync", "reconcile", "--json")
        self.assertNotIn(
            folder_id, json.loads(self.syncthing_state.read_text())["folders"]
        )
        self.assertEqual("preserved\n", sentinel.read_text(encoding="utf-8"))

    def test_target_plan_rejects_unrelated_nonempty_destination(self) -> None:
        destination = self.projects / "collision"
        destination.mkdir()
        (destination / "unrelated.txt").write_text("do not merge\n", encoding="utf-8")
        self.environment["PROJECTCTL_SYNC_ROLE"] = "target"
        plan = {
            "api_version": 1,
            "source_device_id": "SERVER-DEVICE",
            "projects": [
                {
                    "id": "1321b75a-0d91-4f3a-a620-1146aa8f274b",
                    "name": "collision",
                    "title": "Collision",
                }
            ],
        }
        result = self.run_projectctl(
            "sync",
            "apply-plan",
            "--json",
            check=False,
            input_text=json.dumps(plan),
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("non-empty", result.stderr)
        self.assertEqual("do not merge\n", (destination / "unrelated.txt").read_text())


if __name__ == "__main__":
    unittest.main()
