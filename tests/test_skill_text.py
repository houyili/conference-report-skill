import unittest
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "conference-report" / "SKILL.md"


class ConferenceReportSkillTextTests(unittest.TestCase):
    def test_use_stage_resolves_installed_cli_without_source_checkout_fallback(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("Use-stage runs must use the globally installed CLI", text)
        self.assertIn("CONFERENCE_REPORT_CLI", text)
        self.assertIn(".local/cli-path.txt", text)
        self.assertIn("Do not silently fall back", text)

    def test_python_module_fallback_is_developer_only(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        quick_start = text.split("## Pipeline", 1)[0]
        self.assertIn("Developer-only source checkout debugging", quick_start)
        self.assertIn("python -m conference_report.cli", quick_start)
        self.assertNotIn("If working from a source checkout", quick_start)

    def test_skill_defaults_to_agent_writer_with_one_subagent_per_talk(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("--writer agent", text)
        self.assertIn("one subagent per", text.lower())
        self.assertIn("agent_report_tasks.json", text)
        self.assertIn("does not require an OpenAI API key", text)

    def test_skill_requires_task_manifests_write_limits_and_final_validation(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("agent_slide_cognition_tasks.json", text)
        self.assertIn("agent_qa_tasks.json", text)
        self.assertIn("agent_grounding_tasks.json", text)
        self.assertIn("allowed_write_paths", text)
        self.assertIn("--phase agent-tasks", text)
        self.assertIn("--phase final", text)
        self.assertIn("sequential", text.lower())


if __name__ == "__main__":
    unittest.main()
