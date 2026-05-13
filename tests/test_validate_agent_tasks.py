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


def write_required_agent_outputs(
    out: Path,
    *,
    report_text: str | None = None,
    write_provenance: bool = True,
    provenance_worker_type: str = "subagent",
) -> None:
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
        intermediate_outputs = list(task.get("intermediate_output_paths", []))
        if task.get("synthesis_path") and task["synthesis_path"] not in intermediate_outputs:
            intermediate_outputs.append(task["synthesis_path"])
        for output in intermediate_outputs:
            path = Path(output)
            if path.name != "talk_synthesis.md":
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "# Talk synthesis\n\n"
                "## Core question / 核心问题\n\n"
                "The talk asks how to interpret a method slide as the setup for the later evaluation protocol.\n\n"
                "## Method / 方法\n\n"
                "The method uses a shared preparation protocol so the comparison is explained before evaluation claims are made.\n\n"
                "## Result / 结果\n\n"
                "The result chain in this fixture is intentionally small: the method slide supports the later report finding about the comparison protocol.\n\n"
                "## Slide role map\n\n"
                "- Slide 1 introduces the method and should be treated as the core setup slide, not as an evidence-only page.\n\n",
                encoding="utf-8",
            )
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
        if write_provenance:
            provenance_path = Path(
                task.get("execution_provenance_path")
                or Path(task.get("talk_dir", "")).joinpath("agent_execution", "report_writer_provenance.json")
            )
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            provenance_allowed_paths = list(task.get("allowed_write_paths", task["output_paths"]))
            if str(provenance_path.resolve()) not in provenance_allowed_paths:
                provenance_allowed_paths.append(str(provenance_path.resolve()))
            outputs_written = task["output_paths"] + intermediate_outputs + [str(provenance_path.resolve())]
            write_json(
                provenance_path,
                {
                    "host_agent_framework": "codex",
                    "worker_type": provenance_worker_type,
                    "worker_id": "subagent-test-worker",
                    "isolation_scope": "single_report",
                    "assigned_task_id": task["task_id"],
                    "assigned_slug": task["slug"],
                    "topic_understanding_confirmed": True,
                    "input_paths_read": task["input_paths"] + task.get("dependency_output_paths", []),
                    "output_paths_written": outputs_written,
                    "allowed_write_paths": provenance_allowed_paths,
                },
            )


class AgentTaskValidationTests(unittest.TestCase):
    def write_dependency_outputs(self, out: Path, *, valid_cognition: bool = True) -> None:
        for task in read_json(out / "agent_slide_cognition_tasks.json"):
            for output in task["output_paths"]:
                path = Path(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                if valid_cognition:
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
                else:
                    write_json(path, {"visual_summary": "Too shallow", "confidence": 0.4})
        for task in read_json(out / "agent_qa_tasks.json"):
            for output in task["output_paths"]:
                path = Path(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                write_json(path, {"qa_pairs": [], "uncertainties": ["No reliable QA pair was detected."], "confidence": 0.7})

    def test_final_validation_fails_until_all_agent_outputs_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_evidence_scaffold(out)
            make_talk(out, "talk_one", "Talk One")
            with mock.patch(
                "conference_report.report.ocr_slide_text",
                return_value="Method slide with benchmark ranking protocol, evaluation setup, and training details",
            ):
                generate_reports(out, make_cfg(), writer="agent")

            task_phase = validate_run(out, phase="agent-tasks")
            self.assertTrue(task_phase["ok"], task_phase)

            final_before = validate_run(out, phase="final")
            self.assertFalse(final_before["ok"])
            self.assertTrue(any("Missing task output" in error for error in final_before["errors"]))
            self.assertTrue(any("report-writing subagents" in error for error in final_before["errors"]))

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

    def test_agent_tasks_validation_checks_existing_dependency_outputs_and_refreshes_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_evidence_scaffold(out)
            make_talk(out, "talk_one", "Talk One")
            with mock.patch(
                "conference_report.report.ocr_slide_text",
                return_value="Method slide with benchmark ranking protocol, evaluation setup, and training details",
            ):
                generate_reports(out, make_cfg(), writer="agent")

            initial = validate_run(out, phase="agent-tasks")
            self.assertTrue(initial["ok"], initial)
            initial_dispatch = read_json(out / "agent_report_dispatch_plan.json")
            self.assertFalse(initial_dispatch["workers"][0]["dependencies_ready"])
            self.assertEqual(initial_dispatch["workers"][0]["dependency_status"]["missing"], 2)

            self.write_dependency_outputs(out, valid_cognition=False)
            invalid = validate_run(out, phase="agent-tasks")
            self.assertFalse(invalid["ok"])
            self.assertTrue(any("main_claims" in error for error in invalid["errors"]))
            invalid_dispatch = read_json(out / "agent_report_dispatch_plan.json")
            self.assertFalse(invalid_dispatch["workers"][0]["dependencies_ready"])
            self.assertEqual(invalid_dispatch["workers"][0]["dependency_status"]["invalid"], 1)

            self.write_dependency_outputs(out, valid_cognition=True)
            ready = validate_run(out, phase="agent-tasks")
            self.assertTrue(ready["ok"], ready)
            dispatch = read_json(out / "agent_report_dispatch_plan.json")
            self.assertTrue(dispatch["workers"][0]["dependencies_ready"])
            self.assertEqual(dispatch["dependencies_ready_count"], 1)
            self.assertEqual(dispatch["workers"][0]["dependency_status"]["existing"], 2)
            self.assertEqual(dispatch["workers"][0]["dependency_status"]["missing"], 0)
            self.assertTrue(read_json(out / "agent_dependency_status.json")["ok"])

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

    def test_final_validation_rejects_missing_report_subagent_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_evidence_scaffold(out)
            make_talk(out, "talk_one", "Talk One")
            with mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"):
                generate_reports(out, make_cfg(), writer="agent")

            write_required_agent_outputs(out, write_provenance=False)
            result = validate_run(out, phase="final")

            self.assertFalse(result["ok"])
            self.assertTrue(any("Missing report execution provenance" in error for error in result["errors"]))
            self.assertTrue(any("subagents" in error and "authorized" in error for error in result["errors"]))

    def test_final_validation_rejects_report_written_without_subagent(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_evidence_scaffold(out)
            make_talk(out, "talk_one", "Talk One")
            with mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"):
                generate_reports(out, make_cfg(), writer="agent")

            write_required_agent_outputs(out, provenance_worker_type="same_context")
            result = validate_run(out, phase="final")

            self.assertFalse(result["ok"])
            self.assertTrue(any("worker_type must be subagent" in error for error in result["errors"]))

    def test_legacy_report_task_without_provenance_path_can_be_repaired_with_inferred_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_evidence_scaffold(out)
            make_talk(out, "talk_one", "Talk One")
            with mock.patch("conference_report.report.ocr_slide_text", return_value="Method slide"):
                generate_reports(out, make_cfg(), writer="agent")
            tasks = read_json(out / "agent_report_tasks.json")
            legacy_provenance = Path(tasks[0]["execution_provenance_path"])
            del tasks[0]["execution_provenance_path"]
            del tasks[0]["required_provenance"]
            del tasks[0]["requires_subagent"]
            tasks[0]["allowed_write_paths"] = [tasks[0]["report_path"], tasks[0]["synthesis_path"]]
            write_json(out / "agent_report_tasks.json", tasks)

            write_required_agent_outputs(out)
            result = validate_run(out, phase="final")

            self.assertTrue(legacy_provenance.exists())
            self.assertTrue(result["ok"], result)

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
