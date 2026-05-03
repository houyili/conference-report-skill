import importlib.util
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
