from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conference_report.config import DEFAULT_CONFIG
from conference_report.report import generate_reports
from conference_report.utils import read_json, write_json
from conference_report.validate import validate_run

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


def make_evidence_scaffold(out: Path) -> None:
    (out / "asr").mkdir(parents=True)
    (out / "asr" / "timeline.txt").write_text(
        "[00:00:01.000] This slide explains the method.\n"
        "[00:00:11.000] The speaker discusses evaluation.\n",
        encoding="utf-8",
    )
    (out / "slides_original").mkdir()
    (out / "slides_original" / "slide.png").write_bytes(b"not-a-real-png")
    (out / "slides_dedup").mkdir()
    (out / "slides_dedup" / "slide.png").write_bytes(b"not-a-real-png")
    write_json(
        out / "slide_intervals.json",
        [
            {
                "cluster_id": "slide-0001",
                "representative_time": "00:00:00.000",
                "representative_path": str(out / "slides_dedup" / "slide.png"),
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "start_time": "00:00:00.000",
                "end_time": "00:00:10.000",
                "source_times": ["00:00:00.000"],
                "source_paths": [str(out / "slides_original" / "slide.png")],
            }
        ],
    )
    (out / "segmentation").mkdir()
    write_json(out / "segmentation" / "talks.json", [{"talk_id": "talk_one", "slug": "talk_one", "reportable": True}])


def write_required_agent_outputs(out: Path, *, report_text: str | None = None) -> None:
    for manifest_name in ["agent_slide_cognition_tasks.json", "agent_qa_tasks.json", "agent_grounding_tasks.json"]:
        for task in read_json(out / manifest_name):
            for output in task["output_paths"]:
                path = Path(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                if task["stage"] == "slide_cognition":
                    write_json(
                        path,
                        {
                            "visual_summary": "The slide introduces a method page that defines how the comparison protocol is set up.",
                            "speaker_intent": "The speaker uses this page to explain why the method matters before discussing evaluation.",
                            "main_claims": ["The method slide establishes the comparison protocol used in the talk."],
                            "method_details": ["The talk compares models under a shared preparation protocol."],
                            "experiment_or_result": ["The later evaluation depends on this protocol."],
                            "numbers_and_entities": ["method", "comparison protocol"],
                            "asr_corrections": [],
                            "uncertainties": [],
                            "confidence": 0.8,
                        },
                    )
                elif task["stage"] == "qa_detection":
                    write_json(path, {"qa_pairs": [], "uncertainties": ["No reliable QA pair was detected in this short test timeline."], "confidence": 0.7})
                elif task["stage"] == "grounding_review":
                    write_json(
                        path,
                        {
                            "checked_claims": [
                                {
                                    "claim": "The method slide establishes the comparison protocol used in the talk.",
                                    "evidence_refs": ["slide 1", "00:00:01.000"],
                                    "status": "supported",
                                }
                            ],
                            "unsupported_claims": [],
                            "missing_coverage": [],
                            "template_or_style_issues": [],
                            "requires_revision": False,
                            "confidence": 0.8,
                        },
                    )
    for task in read_json(out / "agent_report_tasks.json"):
        for output in task["output_paths"]:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                report_text
                or "# Talk One\n\n"
                "## 摘要\n\n这场 talk 的第一张方法页说明，报告后续比较建立在 shared preparation protocol 上。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- The method slide establishes the comparison protocol used in the talk, so later evaluation should be read through that protocol.\n\n"
                "## 逐页 PPT 解读\n\n### 第 1 张 PPT (00:00:00.000 - 00:00:10.000)\n\n解释。\n\n"
                "## QA\n\n未能可靠形成 QA：No reliable QA pair was detected in this short test timeline.\n",
                encoding="utf-8",
            )


class AgentTaskValidationTests(unittest.TestCase):
    def test_final_validation_fails_until_all_agent_outputs_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_evidence_scaffold(out)
            make_talk(out, "talk_one", "Talk One")
            with mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"):
                generate_reports(out, make_cfg(), writer="agent")

            task_phase = validate_run(out, phase="agent-tasks")
            self.assertTrue(task_phase["ok"], task_phase)

            final_before = validate_run(out, phase="final")
            self.assertFalse(final_before["ok"])
            self.assertTrue(any("Missing task output" in error for error in final_before["errors"]))

            write_required_agent_outputs(out)
            final_after = validate_run(out, phase="final")
            self.assertTrue(final_after["ok"], final_after)
            task_validation = read_json(out / "agent_task_validation.json")
            self.assertTrue(task_validation["ok"])
            self.assertTrue(all(item["ok"] for item in task_validation["tasks"]))
            reports_manifest = read_json(out / "reports_manifest.json")
            self.assertEqual(reports_manifest["pending_reports"], [])
            self.assertEqual(reports_manifest["completed_reports"], reports_manifest["planned_reports"])
            self.assertEqual(reports_manifest["reports"], reports_manifest["completed_reports"])
            self.assertTrue(reports_manifest["final_reports"])

    def test_final_validation_rejects_report_missing_required_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_evidence_scaffold(out)
            make_talk(out, "talk_one", "Talk One")
            with mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"):
                generate_reports(out, make_cfg(), writer="agent")

            write_required_agent_outputs(
                out,
                report_text="# Talk One\n\n## 摘要\n\n总结。\n\n## 逐页 PPT 解读\n\n解释。\n",
            )
            result = validate_run(out, phase="final")
            self.assertFalse(result["ok"])
            self.assertTrue(any("Missing required section" in error for error in result["errors"]))

    def test_agent_task_validation_rejects_outputs_outside_allowed_write_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_evidence_scaffold(out)
            make_talk(out, "talk_one", "Talk One")
            with mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"):
                generate_reports(out, make_cfg(), writer="agent")
            tasks = read_json(out / "agent_report_tasks.json")
            tasks[0]["output_paths"] = [str((out / "reports" / "talk_one.md").resolve())]
            tasks[0]["allowed_write_paths"] = [str((out / "other.md").resolve())]
            write_json(out / "agent_report_tasks.json", tasks)

            result = validate_run(out, phase="agent-tasks")
            self.assertFalse(result["ok"])
            self.assertTrue(any("not listed in allowed_write_paths" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
