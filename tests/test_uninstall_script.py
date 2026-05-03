import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "uninstall.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("uninstall_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class UninstallScriptTests(unittest.TestCase):
    def test_parse_pip_show_extracts_required_by(self):
        uninstaller = load_script_module()
        text = "Name: keyring\nVersion: 25.7.0\nRequired-by: anaconda-cloud-auth, conference-report, spyder\n"

        info = uninstaller.parse_pip_show("keyring", text)

        self.assertTrue(info.installed)
        self.assertEqual(info.version, "25.7.0")
        self.assertEqual(info.required_by, ["anaconda-cloud-auth", "conference-report", "spyder"])

    def test_safe_default_uninstalls_project_and_skill_not_shared_packages(self):
        uninstaller = load_script_module()
        packages = [
            uninstaller.PackageInfo("conference-report", True, "0.1.0", []),
            uninstaller.PackageInfo("faster-whisper", True, "1.2.1", ["conference-report"]),
            uninstaller.PackageInfo("keyring", True, "25.7.0", ["spyder"]),
            uninstaller.PackageInfo("openai", True, "2.33.0", []),
        ]

        defaults = uninstaller.default_package_actions(packages)

        self.assertEqual(defaults["conference-report"], True)
        self.assertEqual(defaults["faster-whisper"], True)
        self.assertEqual(defaults["keyring"], False)
        self.assertEqual(defaults["openai"], False)

    def test_safe_default_keeps_asr_package_when_other_projects_require_it(self):
        uninstaller = load_script_module()
        packages = [
            uninstaller.PackageInfo("faster-whisper", True, "1.2.1", ["conference-report", "other-tool"]),
        ]

        defaults = uninstaller.default_package_actions(packages)

        self.assertEqual(defaults["faster-whisper"], False)

    def test_candidate_skill_installs_discovers_existing_skill_dirs(self):
        uninstaller = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_skill = home / ".codex" / "skills" / "conference-report"
            codex_skill.mkdir(parents=True)
            other_root = home / "agent-skills"
            other_skill = other_root / "conference-report"
            other_skill.mkdir(parents=True)

            installs = uninstaller.candidate_skill_installs(
                home,
                {"AGENT_SKILLS_DIR": str(other_root)},
                "conference-report",
            )

            self.assertEqual([item.path for item in installs], [other_skill, codex_skill])

    def test_dedupe_existing_paths_collapses_symlinked_python_aliases(self):
        uninstaller = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_python = root / "python3.11"
            real_python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            python = root / "python"
            python3 = root / "python3"
            try:
                os.symlink(real_python, python)
                os.symlink(real_python, python3)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not available on this platform")

            paths = uninstaller.dedupe_existing_paths([python, python3])

            self.assertEqual(paths, [python])

    def test_select_python_returns_none_when_no_package_and_manual_path_is_blank(self):
        uninstaller = load_script_module()

        with mock.patch.object(uninstaller, "common_python_candidates", return_value=[]):
            with mock.patch("builtins.input", return_value=""):
                python = uninstaller.select_python()

        self.assertIsNone(python)

    def test_remove_tree_deletes_skill_directory(self):
        uninstaller = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "conference-report"
            skill.mkdir()
            (skill / "SKILL.md").write_text("name: conference-report\n", encoding="utf-8")

            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                uninstaller.remove_tree(skill)

            self.assertFalse(skill.exists())
            self.assertIn("Removed", stdout.getvalue())
            self.assertIn(str(skill), stdout.getvalue())

    def test_entrypoint_turns_keyboard_interrupt_into_clean_cancel_message(self):
        uninstaller = load_script_module()

        with mock.patch.object(uninstaller, "main", side_effect=KeyboardInterrupt):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                code = uninstaller.entrypoint()

        self.assertEqual(code, 130)
        self.assertIn("Uninstall cancelled.", stdout.getvalue())

    def test_uninstall_packages_runs_pip_uninstall_once(self):
        uninstaller = load_script_module()
        with mock.patch.object(uninstaller.subprocess, "check_call") as check_call:
            uninstaller.uninstall_packages(Path("/env/bin/python"), ["conference-report", "faster-whisper"])

        check_call.assert_called_once_with(
            ["/env/bin/python", "-m", "pip", "uninstall", "-y", "conference-report", "faster-whisper"],
            cwd=uninstaller.ROOT,
        )

    def test_brew_uninstall_warning_never_includes_ffmpeg_by_default(self):
        uninstaller = load_script_module()

        warning = uninstaller.system_tool_policy_text()

        self.assertIn("tesseract", warning)
        self.assertIn("ffmpeg", warning)
        self.assertIn("never", warning.lower())


if __name__ == "__main__":
    unittest.main()
