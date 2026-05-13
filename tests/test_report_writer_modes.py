import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conference_report.config import DEFAULT_CONFIG
from conference_report.report import generate_reports
from conference_report.utils import read_json, write_json


def make_cfg():
    return copy.deepcopy(DEFAULT_CONFIG)


def make_talk(root: Path, slug: str, title: str) -> Path:
    talk_dir = root / "talks" / slug
    slides_dir = talk_dir / "slides"
    slides_dir.mkdir(parents=True)
    slide = slides_dir / "slide.png"
    slide.write_bytes(b"not-a-real-png")
    write_json(
        talk_dir / "metadata.json",
        {
            "slug": slug,
            "title": title,
            "speakers": ["Ada"],
            "aligned_start": "00:00:00.000",
            "aligned_end": "00:01:00.000",
        },
    )
    write_json(
        talk_dir / "slide_intervals.json",
        [
            {
                "representative_path": str(slide),
                "talk_slide_path": str(slide),
                "start_time": "00:00:00.000",
                "end_time": "00:00:10.000",
                "start_seconds": 0.0,
                "end_seconds": 10.0,
            }
        ],
    )
    (talk_dir / "timeline.txt").write_text("[00:00:01.000] This slide explains the method.\n", encoding="utf-8")
    return talk_dir


class ReportWriterModeTests(unittest.TestCase):
    def test_agent_writer_creates_one_task_per_talk_without_openai_key_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_talk(out, "talk_one", "Talk One")
            make_talk(out, "talk_two", "Talk Two")

            with (
                mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"),
                mock.patch("conference_report.report.get_openai_api_key", side_effect=AssertionError("key lookup not allowed")),
            ):
                report_paths = generate_reports(out, make_cfg(), writer="agent")

            tasks = read_json(out / "agent_report_tasks.json")
            self.assertEqual(len(tasks), 2)
            self.assertTrue(all(item["stage"] == "report_write" for item in tasks))
            self.assertTrue(all(item["task_id"].startswith("report:") for item in tasks))
            self.assertEqual(len({item["report_path"] for item in tasks}), 2)
            self.assertEqual({Path(item["talk_dir"]).name for item in tasks}, {"talk_one", "talk_two"})
            self.assertTrue(all(Path(item["prompt_path"]).exists() for item in tasks))
            self.assertTrue(all(Path(item["evidence_path"]).exists() for item in tasks))
            self.assertTrue(all(Path(item["slides_dir"]).exists() for item in tasks))
            self.assertTrue(all(not Path(item["report_path"]).exists() for item in tasks))
            self.assertTrue(all(item["output_paths"] == [item["report_path"]] for item in tasks))
            self.assertTrue(all("execution_provenance_path" in item for item in tasks))
            self.assertTrue(all(item["report_path"] in item["allowed_write_paths"] for item in tasks))
            self.assertTrue(all("synthesis_path" in item for item in tasks))
            self.assertTrue(all(item["synthesis_path"] in item["allowed_write_paths"] for item in tasks))
            self.assertTrue(all(item["intermediate_output_paths"] == [item["synthesis_path"]] for item in tasks))
            self.assertTrue(all(item["execution_provenance_path"] in item["allowed_write_paths"] for item in tasks))
            self.assertTrue(all("slide_identity_contract" in item for item in tasks))
            self.assertTrue(all("摘要" in item["required_sections"] for item in tasks))
            self.assertTrue(all("QA" in item["required_sections"] for item in tasks))
            self.assertTrue(all("validation_rules" in item for item in tasks))
            self.assertTrue(all("subagent_contract" in item for item in tasks))
            self.assertTrue(all(item["requires_subagent"] is True for item in tasks))
            self.assertTrue(all(item["required_provenance"]["worker_type"] == "subagent" for item in tasks))
            self.assertTrue(all(item["required_provenance"]["isolation_scope"] == "single_report" for item in tasks))
            self.assertTrue(all("quality_contract" in item for item in tasks))
            for task in tasks:
                contract_text = "\n".join(task["subagent_contract"] + task["quality_contract"])
                self.assertIn("one clean subagent context per report", contract_text)
                self.assertIn("topic-level understanding before writing", contract_text)
                self.assertIn("talk_synthesis.md", contract_text)
                self.assertIn("OCR, ASR, and screenshots are evidence for understanding", contract_text)
            self.assertEqual([str(path.resolve()) for path in report_paths], [item["report_path"] for item in tasks])

            manifest = read_json(out / "reports_manifest.json")
            self.assertEqual(manifest["writer_mode"], "agent")
            self.assertFalse(manifest["final_reports"])
            self.assertEqual(manifest["mode"], "agent_subagents")
            self.assertEqual(manifest["reports"], [])
            self.assertEqual(sorted(manifest["planned_reports"]), sorted(item["report_path"] for item in tasks))
            self.assertEqual(manifest["completed_reports"], [])
            self.assertEqual(sorted(manifest["pending_reports"]), sorted(item["report_path"] for item in tasks))
            self.assertEqual(manifest["task_manifests"]["report_write"], str((out / "agent_report_tasks.json").resolve()))
            self.assertEqual(manifest["task_manifests"]["report_dispatch"], str((out / "agent_report_dispatch_plan.json").resolve()))
            self.assertIn("slide_cognition", manifest["task_manifests"])
            self.assertIn("qa_detection", manifest["task_manifests"])
            self.assertIn("grounding_review", manifest["task_manifests"])

            dispatch = read_json(out / "agent_report_dispatch_plan.json")
            self.assertTrue(dispatch["requires_subagents"])
            self.assertEqual(dispatch["required_report_subagents"], 2)
            self.assertEqual(dispatch["subagent_required_stage"], "report_write")
            self.assertIn("请用户明确授权为每个 report task 启动独立 subagent", dispatch["authorization_message"])
            self.assertEqual(len(dispatch["workers"]), 2)
            self.assertEqual({worker["slug"] for worker in dispatch["workers"]}, {"talk_one", "talk_two"})
            self.assertTrue(all(worker["worker_type"] == "subagent" for worker in dispatch["workers"]))
            self.assertTrue(all(worker["isolation_scope"] == "single_report" for worker in dispatch["workers"]))
            self.assertTrue(all(worker["task"]["task_id"].startswith("report:") for worker in dispatch["workers"]))
            self.assertTrue(all(worker["dependency_validation_phase"] == "agent-tasks" for worker in dispatch["workers"]))
            self.assertTrue(all(worker["expected_dependency_count"] == len(worker["dependency_output_paths"]) for worker in dispatch["workers"]))
            self.assertTrue(all(worker["dependency_status"]["missing"] == worker["expected_dependency_count"] for worker in dispatch["workers"]))
            self.assertTrue(all(worker["dependencies_ready"] is False for worker in dispatch["workers"]))
            self.assertTrue(all(worker["intermediate_output_paths"] == worker["task"]["intermediate_output_paths"] for worker in dispatch["workers"]))
            self.assertTrue(all(worker["execution_provenance_path"] in worker["allowed_write_paths"] for worker in dispatch["workers"]))
            self.assertIn("evidence", {item["writer"] for item in dispatch["fallback_options"]})
            self.assertIn("openai", {item["writer"] for item in dispatch["fallback_options"]})

    def test_agent_writer_evidence_separates_local_and_original_slide_indices_after_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            talk_dir = make_talk(out, "talk_one", "Talk One")
            slide2 = talk_dir / "slides" / "slide2.png"
            slide2.write_bytes(b"not-a-real-png")
            write_json(
                talk_dir / "slide_intervals.json",
                [
                    {
                        "representative_path": str((talk_dir / "slides" / "slide.png").resolve()),
                        "talk_slide_path": str((talk_dir / "slides" / "slide.png").resolve()),
                        "start_time": "00:00:00.000",
                        "end_time": "00:00:10.000",
                        "start_seconds": 0.0,
                        "end_seconds": 10.0,
                    },
                    {
                        "representative_path": str(slide2.resolve()),
                        "talk_slide_path": str(slide2.resolve()),
                        "start_time": "00:00:10.000",
                        "end_time": "00:00:20.000",
                        "start_seconds": 10.0,
                        "end_seconds": 20.0,
                    },
                ],
            )
            (talk_dir / "timeline.txt").write_text(
                "[00:00:01.000] Our last paper will be presented by Ada.\n"
                "[00:00:11.000] This slide explains the method.\n",
                encoding="utf-8",
            )

            with mock.patch(
                "conference_report.report.ocr_slide_text",
                side_effect=[
                    "ICLR",
                    "Method slide with benchmark ranking protocol, evaluation setup, and training details",
                ],
            ):
                generate_reports(out, make_cfg(), writer="agent")

            evidence = read_json(talk_dir / "evidence.json")
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]["local_evidence_index"], "1")
            self.assertEqual(evidence[0]["original_slide_index"], "2")
            self.assertEqual(evidence[0]["slide_index"], "2")

    def test_openai_writer_requires_key_before_calling_openai(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_talk(out, "talk_one", "Talk One")

            with (
                mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"),
                mock.patch("conference_report.report.get_openai_api_key", return_value=None),
                mock.patch("conference_report.report.call_responses", side_effect=AssertionError("should not call model")),
            ):
                with self.assertRaises(SystemExit) as raised:
                    generate_reports(out, make_cfg(), writer="openai")

            self.assertIn("OpenAI API key", str(raised.exception))

    def test_auto_writer_keeps_key_and_no_key_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_talk(out, "talk_one", "Talk One")

            with (
                mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"),
                mock.patch("conference_report.report.get_openai_api_key", return_value=None),
            ):
                generate_reports(out, make_cfg(), writer="auto")

            manifest = read_json(out / "reports_manifest.json")
            self.assertEqual(manifest["writer_mode"], "evidence")
            self.assertEqual(manifest["mode"], "evidence_bundle")
            self.assertTrue((out / "reports" / "talk_one.md").exists())

    def test_auto_writer_uses_openai_when_key_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_talk(out, "talk_one", "Talk One")

            with (
                mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"),
                mock.patch("conference_report.report.get_openai_api_key", return_value="key"),
                mock.patch("conference_report.report.call_responses", side_effect=["slide note", "## 摘要\noverview"]),
            ):
                generate_reports(out, make_cfg(), writer="auto")

            manifest = read_json(out / "reports_manifest.json")
            self.assertEqual(manifest["writer_mode"], "openai")
            self.assertEqual(manifest["mode"], "openai_responses")
            self.assertTrue(manifest["final_reports"])
            self.assertIn("slide note", (out / "reports" / "talk_one.md").read_text(encoding="utf-8"))

    def test_dry_run_report_remains_evidence_mode_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_talk(out, "talk_one", "Talk One")

            with mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"):
                generate_reports(out, make_cfg(), dry_run=True, writer="openai")

            manifest = read_json(out / "reports_manifest.json")
            self.assertEqual(manifest["writer_mode"], "evidence")
            self.assertEqual(manifest["mode"], "evidence_bundle")


if __name__ == "__main__":
    unittest.main()
