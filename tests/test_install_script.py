import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "install.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("install_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstallScriptHelperTests(unittest.TestCase):
    def test_dev_dependency_summary_explains_pytest_is_for_contributors(self):
        installer = load_script_module()

        summary = installer.dev_dependency_summary()

        self.assertIn("pytest", summary)
        self.assertIn("contributors", summary.lower())
        self.assertIn("not required", summary.lower())

    def test_candidate_skill_roots_uses_existing_local_dirs_and_env_vars(self):
        installer = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex = home / ".codex" / "skills"
            claude = home / ".claude" / "skills"
            codex.mkdir(parents=True)
            claude.mkdir(parents=True)
            custom = home / "custom-agent" / "skills"
            custom.mkdir(parents=True)

            candidates = installer.candidate_skill_roots(
                home,
                {
                    "ANTIGRAVITY_SKILLS_DIR": str(custom),
                    "OPENCLAW_SKILLS_DIR": str(home / "missing" / "skills"),
                },
            )

            paths = [item.path for item in candidates]
            self.assertIn(codex, paths)
            self.assertIn(claude, paths)
            self.assertIn(custom, paths)
            self.assertNotIn(home / "missing" / "skills", paths)

    def test_inspect_package_reports_version_and_clean_pip_check(self):
        installer = load_script_module()
        pip_show = mock.Mock(returncode=0, stdout="Name: faster-whisper\nVersion: 1.1.1\n", stderr="")
        pip_check = mock.Mock(returncode=0, stdout="No broken requirements found.\n", stderr="")

        with mock.patch.object(installer.subprocess, "run", side_effect=[pip_show, pip_check]):
            status = installer.inspect_package(Path("/tmp/python"), "faster-whisper")

        self.assertTrue(status.installed)
        self.assertEqual(status.version, "1.1.1")
        self.assertFalse(status.has_conflicts)
        self.assertIn("No broken requirements", status.conflict_report)

    def test_inspect_package_reports_missing_package_without_pip_check(self):
        installer = load_script_module()
        pip_show = mock.Mock(returncode=1, stdout="", stderr="WARNING: Package(s) not found")

        with mock.patch.object(installer.subprocess, "run", return_value=pip_show) as run:
            status = installer.inspect_package(Path("/tmp/python"), "faster-whisper")

        self.assertFalse(status.installed)
        self.assertIsNone(status.version)
        self.assertFalse(status.has_conflicts)
        self.assertEqual(run.call_count, 1)

    def test_run_reports_command_failure_without_traceback(self):
        installer = load_script_module()
        error = installer.subprocess.CalledProcessError(1, ["python", "-m", "pip", "install", "-e", "."])

        with mock.patch.object(installer.subprocess, "check_call", side_effect=error):
            with self.assertRaises(SystemExit) as raised:
                installer.run(["python", "-m", "pip", "install", "-e", "."])

        message = str(raised.exception)
        self.assertIn("Command failed", message)
        self.assertIn("pip install", message)
        self.assertIn("network access", message)

    def test_missing_required_tool_warning_names_tools_and_blocks_build_confidence(self):
        installer = load_script_module()

        warning = installer.missing_required_tool_warning(["ffmpeg", "ffprobe"])

        self.assertIn("ffmpeg", warning)
        self.assertIn("ffprobe", warning)
        self.assertIn("cannot run the full build pipeline", warning.lower())

    def test_conda_executable_checks_common_anaconda_paths_when_not_on_path(self):
        installer = load_script_module()
        fake_conda = Path("/opt/anaconda3/condabin/conda")

        self.assertEqual(
            installer.conda_executable(
                which=lambda _name: None,
                exists=lambda path: path == fake_conda,
            ),
            str(fake_conda),
        )

    def test_python_environment_choices_prefer_new_conda_when_no_compatible_python(self):
        installer = load_script_module()

        options, default = installer.python_environment_choices(
            compatible_python=None,
            conda="/opt/anaconda3/condabin/conda",
            current_is_compatible=False,
        )

        self.assertEqual(default, 1)
        self.assertEqual(options[0][0], "conda-create")

    def test_base_conda_warning_discourages_polluting_base(self):
        installer = load_script_module()

        warning = installer.conda_env_warning("base")

        self.assertIn("base", warning.lower())
        self.assertIn("not recommended", warning.lower())
        self.assertIn("new conda environment", warning.lower())

    def test_command_path_uses_selected_python_bin_directory(self):
        installer = load_script_module()

        command = installer.command_path_for_python(Path("/opt/anaconda3/envs/demo/bin/python"), "conference-report")

        self.assertEqual(command, Path("/opt/anaconda3/envs/demo/bin/conference-report"))

    def test_dependency_check_warning_reports_conflicts_without_claiming_success(self):
        installer = load_script_module()

        warning = installer.dependency_check_warning("package-a has requirement x, but you have y")

        self.assertIn("dependency conflicts", warning.lower())
        self.assertIn("package-a", warning)


if __name__ == "__main__":
    unittest.main()
