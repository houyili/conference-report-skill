import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "install_agent_skill.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("install_agent_skill", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class InstallAgentSkillTests(unittest.TestCase):
    def make_skill_source(self, root: Path) -> Path:
        source = root / "skills" / "conference-report"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("---\nname: conference-report\n---\n", encoding="utf-8")
        (source / "agents").mkdir()
        (source / "agents" / "openai.yaml").write_text("display_name: Conference Report\n", encoding="utf-8")
        return source

    def test_install_requires_user_supplied_target_and_copies_skill(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill_source(root)
            target_root = root / "agent-skills"

            installed = installer.install_skill(source, [target_root], "conference-report", upgrade=False)

            target = target_root / "conference-report"
            self.assertEqual(installed, [target])
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "---\nname: conference-report\n---\n")
            self.assertTrue((target / "agents" / "openai.yaml").exists())

    def test_install_records_user_local_cli_path_when_provided(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill_source(root)
            target_root = root / "agent-skills"
            cli = root / "env" / "bin" / "conference-report"

            installer.install_skill(source, [target_root], "conference-report", upgrade=False, cli_path=cli)

            target = target_root / "conference-report"
            self.assertEqual(
                (target / ".local" / "cli-path.txt").read_text(encoding="utf-8"),
                f"{cli.resolve(strict=False)}\n",
            )
            self.assertFalse((source / ".local").exists())

    def test_upgrade_preserves_existing_cli_path_when_not_provided(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill_source(root)
            target_root = root / "agent-skills"
            cli = root / "env" / "bin" / "conference-report"
            installer.install_skill(source, [target_root], "conference-report", upgrade=False, cli_path=cli)

            installer.install_skill(source, [target_root], "conference-report", upgrade=True)

            target = target_root / "conference-report"
            self.assertEqual(
                (target / ".local" / "cli-path.txt").read_text(encoding="utf-8"),
                f"{cli.resolve(strict=False)}\n",
            )

    def test_main_auto_records_visible_cli_path_when_cli_path_omitted(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill_source(root)
            target_root = root / "agent-skills"
            cli = root / "visible" / "conference-report"
            cli.parent.mkdir(parents=True)
            cli.write_text("#!/bin/sh\n", encoding="utf-8")

            with mock.patch.object(installer.shutil, "which", return_value=str(cli)):
                installer.main([
                    "install",
                    "--source",
                    str(source),
                    "--target-dir",
                    str(target_root),
                ])

            target = target_root / "conference-report"
            self.assertEqual(
                (target / ".local" / "cli-path.txt").read_text(encoding="utf-8"),
                f"{cli.resolve(strict=False)}\n",
            )

    def test_install_refuses_to_overwrite_existing_skill(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill_source(root)
            target_root = root / "agent-skills"
            installer.install_skill(source, [target_root], "conference-report", upgrade=False)

            with self.assertRaises(FileExistsError):
                installer.install_skill(source, [target_root], "conference-report", upgrade=False)

    def test_upgrade_replaces_stale_global_copy(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_skill_source(root)
            target_root = root / "agent-skills"
            installer.install_skill(source, [target_root], "conference-report", upgrade=False)
            stale = target_root / "conference-report" / "stale.txt"
            stale.write_text("old", encoding="utf-8")

            installed = installer.install_skill(source, [target_root], "conference-report", upgrade=True)

            self.assertEqual(installed, [target_root / "conference-report"])
            self.assertFalse(stale.exists())
            self.assertTrue((target_root / "conference-report" / "SKILL.md").exists())

    def test_installed_skill_roots_only_returns_existing_skill_copies(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex" / "skills"
            claude_root = home / ".claude" / "skills"
            codex_skill = codex_root / "conference-report"
            codex_skill.mkdir(parents=True)
            (codex_skill / "SKILL.md").write_text("name: conference-report\n", encoding="utf-8")
            claude_root.mkdir(parents=True)

            candidates = installer.installed_skill_roots(home, {}, "conference-report")

            self.assertEqual(candidates, [("Codex", codex_root, "existing ~/.codex/skills")])

    def test_prompt_for_upgrade_recommends_first_installed_skill_root(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex" / "skills"
            codex_skill = codex_root / "conference-report"
            codex_skill.mkdir(parents=True)
            (codex_skill / "SKILL.md").write_text("name: conference-report\n", encoding="utf-8")

            with mock.patch.object(installer.Path, "home", return_value=home):
                with mock.patch.object(installer.os, "environ", {}):
                    with mock.patch("builtins.input", return_value=""):
                        selected = installer.prompt_for_target_dirs("upgrade", "conference-report")

            self.assertEqual(selected, [codex_root])

    def test_parse_args_allows_interactive_upgrade_without_target_dir(self):
        installer = load_script_module()

        args = installer.parse_args(["upgrade"])

        self.assertEqual(args.command, "upgrade")
        self.assertIsNone(args.target_dir)

    def test_parse_args_accepts_dash_as_interactive_target_hint(self):
        installer = load_script_module()

        args = installer.parse_args(["upgrade", "-"])

        self.assertEqual(args.command, "upgrade")
        self.assertEqual(args.target_hint, "-")

    def test_main_reports_permission_errors_without_traceback(self):
        installer = load_script_module()

        with mock.patch.object(installer, "install_skill", side_effect=PermissionError("denied")):
            with self.assertRaises(SystemExit) as raised:
                installer.main(["upgrade", "--target-dir", "/agent/skills"])

        message = str(raised.exception)
        self.assertIn("Could not modify installed skill target", message)
        self.assertIn("/agent/skills/conference-report", message)
        self.assertIn("denied", message)


if __name__ == "__main__":
    unittest.main()
