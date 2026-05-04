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

    def test_skill_documents_agent_gates_validate_then_resume(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("--agent-gates dedupe,report", text)
        self.assertIn("conference-report status", text)
        self.assertIn("conference-report resume", text)
        self.assertIn("--phase dedupe-review", text)
        self.assertIn("Agent 不决定下一步", text)
        self.assertIn("不要猜下一步", text)
        self.assertNotIn("/Users/jyxc-dz-0100301", text)

    def test_skill_quick_start_uses_run_local_config_and_fast_profile(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        quick_start = text.split("## Agent Gates", 1)[0]
        self.assertIn("init-config", quick_start)
        self.assertIn("--profile fast", quick_start)
        self.assertIn("$RUN/config.yaml", quick_start)
        self.assertIn("--config \"$RUN/config.yaml\"", quick_start)
        self.assertIn("skips optional audio preservation", quick_start)
        self.assertNotIn("--config config.example.yaml", quick_start)

    def test_skill_documents_report_quality_and_revision_gate(self):
        text = SKILL_PATH.read_text(encoding="utf-8")

        self.assertIn("--phase report-quality", text)
        self.assertIn("report_revision", text)
        self.assertIn("不要把 OCR/ASR 机械填进报告", text)
        self.assertIn("validate → revise → resume", text)


if __name__ == "__main__":
    unittest.main()
