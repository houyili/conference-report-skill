import unittest
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "conference-report" / "SKILL.md"


class ConferenceReportSkillTextTests(unittest.TestCase):
    def test_use_stage_stops_when_global_cli_is_not_visible(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("Use-stage runs must use the globally installed CLI", text)
        self.assertIn("If `conference-report` is not found, stop", text)
        self.assertIn("Do not silently fall back", text)

    def test_python_module_fallback_is_developer_only(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        quick_start = text.split("## Pipeline", 1)[0]
        self.assertIn("Developer-only source checkout debugging", quick_start)
        self.assertIn("python -m conference_report.cli", quick_start)
        self.assertNotIn("If working from a source checkout", quick_start)


if __name__ == "__main__":
    unittest.main()
