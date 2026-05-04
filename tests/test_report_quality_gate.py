from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conference_report import cli
from conference_report.utils import read_json, write_json
from conference_report.validate import validate_run


def make_agent_quality_run(out: Path, *, slug: str = "talk_one") -> dict[str, Path]:
    talk_dir = out / "talks" / slug
    slides_dir = talk_dir / "slides"
    reports_dir = out / "reports"
    slides_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    slide = slides_dir / "slide.png"
    slide.write_bytes(b"not-a-real-png")
    report = reports_dir / f"{slug}.md"
    grounding = reports_dir / f"{slug}.grounding.json"
    cognition = talk_dir / "slide_cognition" / "0001.json"
    qa = talk_dir / "qa" / "qa_pairs.json"
    for path in [cognition, qa]:
        path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        talk_dir / "metadata.json",
        {
            "slug": slug,
            "title": "Talk One",
            "speakers": ["Ada"],
            "aligned_start": "00:00:00.000",
            "aligned_end": "00:10:00.000",
        },
    )
    (talk_dir / "timeline.txt").write_text(
        "[00:00:01.000] The slide explains a method for comparing model rankings after identical preparation.\n"
        "[00:00:20.000] The result is stronger ranking agreement across benchmarks.\n",
        encoding="utf-8",
    )
    (out / "asr").mkdir(parents=True)
    (out / "asr" / "timeline.txt").write_text((talk_dir / "timeline.txt").read_text(encoding="utf-8"), encoding="utf-8")
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
                "representative_path": str((out / "slides_dedup" / "slide.png").resolve()),
                "start_seconds": 0.0,
                "end_seconds": 30.0,
                "start_time": "00:00:00.000",
                "end_time": "00:00:30.000",
                "source_times": ["00:00:00.000"],
                "source_paths": [str((out / "slides_original" / "slide.png").resolve())],
            }
        ],
    )
    (out / "segmentation").mkdir()
    write_json(out / "segmentation" / "talks.json", [{"talk_id": slug, "slug": slug, "reportable": True}])
    write_json(
        talk_dir / "evidence.json",
        [
            {
                "slide_index": "1",
                "time": "00:00:00.000 - 00:00:30.000",
                "image": str(slide.resolve()),
                "ocr_text": "Method: train-before-test. Result: ranking agreement improves across benchmarks.",
                "asr_text": "The slide explains a method for comparing model rankings after identical preparation.",
                "role": "方法页",
            }
        ],
    )
    write_json(
        out / "reports_manifest.json",
        {
            "writer_mode": "agent",
            "final_reports": False,
            "reports": [],
            "planned_reports": [str(report.resolve())],
            "pending_reports": [str(report.resolve())],
            "task_manifests": {
                "slide_cognition": str((out / "agent_slide_cognition_tasks.json").resolve()),
                "qa_detection": str((out / "agent_qa_tasks.json").resolve()),
                "report_write": str((out / "agent_report_tasks.json").resolve()),
                "grounding_review": str((out / "agent_grounding_tasks.json").resolve()),
            },
            "task_count": 4,
        },
    )
    write_json(
        out / "agent_slide_cognition_tasks.json",
        [
            {
                "task_id": f"slide-cognition:{slug}:0001",
                "stage": "slide_cognition",
                "slug": slug,
                "title": "Talk One",
                "slide_index": 1,
                "time": "00:00:00.000 - 00:00:30.000",
                "input_paths": [str((talk_dir / "evidence.json").resolve()), str(slide.resolve())],
                "output_paths": [str(cognition.resolve())],
                "allowed_write_paths": [str(cognition.resolve())],
                "required_schema": {
                    "visual_summary": "string",
                    "speaker_intent": "string",
                    "main_claims": "array",
                    "method_details": "array",
                    "experiment_or_result": "array",
                    "numbers_and_entities": "array",
                    "asr_corrections": "array",
                    "uncertainties": "array",
                    "confidence": "number",
                },
                "validation_rules": [{"type": "json_fields"}, {"type": "allowed_writes"}],
            }
        ],
    )
    write_json(
        out / "agent_qa_tasks.json",
        [
            {
                "task_id": f"qa-detection:{slug}",
                "stage": "qa_detection",
                "slug": slug,
                "title": "Talk One",
                "input_paths": [str((talk_dir / "timeline.txt").resolve()), str((talk_dir / "evidence.json").resolve())],
                "output_paths": [str(qa.resolve())],
                "allowed_write_paths": [str(qa.resolve())],
                "required_schema": {"qa_pairs": "array", "uncertainties": "array", "confidence": "number"},
                "validation_rules": [{"type": "json_fields"}, {"type": "allowed_writes"}],
            }
        ],
    )
    write_json(
        out / "agent_report_tasks.json",
        [
            {
                "task_id": f"report:{slug}",
                "stage": "report_write",
                "slug": slug,
                "title": "Talk One",
                "talk_dir": str(talk_dir.resolve()),
                "report_path": str(report.resolve()),
                "input_paths": [
                    str((talk_dir / "evidence.json").resolve()),
                    str((talk_dir / "metadata.json").resolve()),
                    str((talk_dir / "timeline.txt").resolve()),
                    str(slides_dir.resolve()),
                ],
                "dependency_output_paths": [str(cognition.resolve()), str(qa.resolve())],
                "output_paths": [str(report.resolve())],
                "allowed_write_paths": [str(report.resolve())],
                "required_sections": ["摘要", "核心 Findings / Experiments / Insights", "逐页 PPT 解读", "QA"],
                "validation_rules": [{"type": "exists"}, {"type": "markdown_required_sections"}, {"type": "allowed_writes"}],
            }
        ],
    )
    write_json(
        out / "agent_grounding_tasks.json",
        [
            {
                "task_id": f"grounding-review:{slug}",
                "stage": "grounding_review",
                "slug": slug,
                "title": "Talk One",
                "input_paths": [str((talk_dir / "evidence.json").resolve())],
                "dependency_output_paths": [str(report.resolve())],
                "output_paths": [str(grounding.resolve())],
                "allowed_write_paths": [str(grounding.resolve())],
                "required_schema": {
                    "checked_claims": "array",
                    "unsupported_claims": "array",
                    "missing_coverage": "array",
                    "template_or_style_issues": "array",
                    "requires_revision": "boolean",
                    "confidence": "number",
                },
                "validation_rules": [{"type": "json_fields"}, {"type": "allowed_writes"}],
            }
        ],
    )
    return {"talk_dir": talk_dir, "slide": slide, "report": report, "grounding": grounding, "cognition": cognition, "qa": qa}


def write_good_agent_outputs(paths: dict[str, Path]) -> None:
    write_json(
        paths["cognition"],
        {
            "visual_summary": "The slide presents train-before-test as a comparison method and states that benchmark rankings become more consistent.",
            "speaker_intent": "The speaker uses this slide to explain why equal benchmark-specific preparation is needed before comparing models.",
            "main_claims": ["Identical preparation before testing makes language model rankings more comparable."],
            "method_details": ["Train each model on the benchmark training split before evaluating on the held-out test split."],
            "experiment_or_result": ["Ranking agreement improves after applying train-before-test."],
            "numbers_and_entities": ["benchmark rankings", "language models"],
            "asr_corrections": [],
            "uncertainties": [],
            "confidence": 0.86,
        },
    )
    write_json(
        paths["qa"],
        {
            "qa_pairs": [
                {
                    "question": "Did the talk explain why direct benchmark rankings disagree?",
                    "answer": "Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.",
                    "time_range": "00:00:01.000 - 00:00:25.000",
                    "evidence_quotes": ["identical preparation", "stronger ranking agreement"],
                    "confidence": 0.74,
                }
            ],
            "uncertainties": [],
            "confidence": 0.74,
        },
    )
    image_link = "../talks/talk_one/slides/slide.png"
    paths["report"].write_text(
        "# Talk One\n\n"
        "## 摘要\n\n"
        "这场 talk 的核心是用 train-before-test 重新定义模型排名比较：先让模型接受相同的 benchmark-specific preparation，再比较测试表现。\n\n"
        "## 核心 Findings / Experiments / Insights\n\n"
        "- 主要 finding: identical preparation before testing makes language model rankings more comparable，并缓解 direct evaluation 中不同 benchmark 排名不一致的问题。\n\n"
        "## 逐页 PPT 解读\n\n"
        "### 第 1 张 PPT (00:00:00.000 - 00:00:30.000)\n\n"
        f"![slide]({image_link})\n\n"
        "这页提出方法和结果：PPT 写出 train-before-test，演讲者说明要在相同准备条件下比较模型。"
        "因此该页不是简单介绍背景，而是在定义后续实验的比较协议。\n\n"
        "## QA\n\n"
        "- Q: Did the talk explain why direct benchmark rankings disagree?\n"
        "- A: Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.\n",
        encoding="utf-8",
    )
    write_json(
        paths["grounding"],
        {
            "checked_claims": [
                {
                    "claim": "Identical preparation before testing makes language model rankings more comparable.",
                    "evidence_refs": ["slide 1", "00:00:01.000 - 00:00:25.000"],
                    "status": "supported",
                }
            ],
            "unsupported_claims": [],
            "missing_coverage": [],
            "template_or_style_issues": [],
            "requires_revision": False,
            "confidence": 0.82,
        },
    )


def write_bad_quality_outputs(paths: dict[str, Path]) -> None:
    write_json(
        paths["cognition"],
        {
            "visible_title": "Method",
            "chart_description": "OCR and ASR summary",
            "key_terms": ["method"],
            "ocr_corrections": [],
            "asr_alignment": "aligned",
            "uncertainties": [],
            "confidence": 0.8,
        },
    )
    write_json(paths["qa"], {"qa_candidates": [{"text": "base model? Oh no. My"}], "uncertainties": [], "confidence": 0.6})
    paths["report"].write_text(
        "# Talk One\n\n## 摘要\n\n总结。\n\n## 核心 Findings / Experiments / Insights\n\n发现。\n\n"
        "## 逐页 PPT 解读\n\n### 第 1 张 PPT\n\n"
        "综合来看，这页的作用是把可见 PPT 内容和讲者说明对齐起来，支撑本 talk 的问题动机、方法、实验或结论之一。\n\n"
        "## QA\n\n碎片。\n",
        encoding="utf-8",
    )
    write_json(paths["grounding"], {"grounded": True, "issues": [], "confidence": 0.8})


class ReportQualityGateTests(unittest.TestCase):
    def test_report_quality_rejects_template_report_and_writes_revision_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n总结。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- 发现。\n\n"
                "## 逐页 PPT 解读\n\n"
                "### 第 1 张 PPT (00:00:00.000 - 00:00:30.000)\n\n"
                "![slide](../talks/talk_one/slides/slide.png)\n\n"
                "这页在报告结构中更像是**实验与结果页**。综合来看，这页的作用是把可见 PPT 内容和讲者说明对齐起来，支撑本 talk 的问题动机、方法、实验或结论之一；若 OCR/ASR 有误，应以截图中的可见文字为优先依据。\n\n"
                "## QA\n\n- [00:00:01.000] question fragment?\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertFalse(result["ok"])
            quality = read_json(out / "report_quality_validation.json")
            self.assertFalse(quality["ok"])
            self.assertTrue(any("template repetition" in error for error in quality["reports"][0]["errors"]))
            self.assertTrue((out / "agent_report_revision_tasks.json").exists())

    def test_report_quality_writes_full_repair_plan_for_upstream_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_bad_quality_outputs(paths)
            qa_candidates = paths["talk_dir"] / "qa" / "qa_candidates.json"
            qa_candidates.write_text(paths["qa"].read_text(encoding="utf-8"), encoding="utf-8")
            qa_tasks = read_json(out / "agent_qa_tasks.json")
            qa_tasks[0]["output_paths"] = [str(qa_candidates.resolve())]
            qa_tasks[0]["allowed_write_paths"] = [str(qa_candidates.resolve())]
            qa_tasks[0]["required_schema"] = {"qa_candidates": "array", "uncertainties": "array", "confidence": "number"}
            write_json(out / "agent_qa_tasks.json", qa_tasks)

            result = validate_run(out, phase="report-quality")

            self.assertFalse(result["ok"])
            repair_plan = read_json(out / "agent_quality_repair_plan.json")
            self.assertEqual(repair_plan["blocked_gate"], "report_quality_repair")
            self.assertEqual(
                repair_plan["stages"],
                ["slide_cognition_revision", "qa_revision", "report_revision", "grounding_revision"],
            )
            self.assertIn("agent_slide_cognition_revision_tasks.json", repair_plan["task_manifests"].values())
            self.assertIn("agent_qa_revision_tasks.json", repair_plan["task_manifests"].values())
            self.assertIn("agent_report_revision_tasks.json", repair_plan["task_manifests"].values())
            self.assertIn("agent_grounding_revision_tasks.json", repair_plan["task_manifests"].values())

            cognition_tasks = read_json(out / "agent_slide_cognition_revision_tasks.json")
            self.assertEqual([task["stage"] for task in cognition_tasks], ["slide_cognition_revision"])
            self.assertEqual(cognition_tasks[0]["output_paths"], [str(paths["cognition"].resolve())])
            self.assertEqual(cognition_tasks[0]["allowed_write_paths"], cognition_tasks[0]["output_paths"])

            qa_revision_tasks = read_json(out / "agent_qa_revision_tasks.json")
            self.assertEqual(qa_revision_tasks[0]["stage"], "qa_revision")
            self.assertEqual(qa_revision_tasks[0]["output_paths"], [str(paths["qa"].resolve())])
            self.assertEqual(qa_revision_tasks[0]["allowed_write_paths"], qa_revision_tasks[0]["output_paths"])

            report_revision_tasks = read_json(out / "agent_report_revision_tasks.json")
            self.assertEqual(report_revision_tasks[0]["stage"], "report_revision")
            self.assertEqual(report_revision_tasks[0]["output_paths"], [str(paths["report"].resolve())])

            grounding_revision_tasks = read_json(out / "agent_grounding_revision_tasks.json")
            self.assertEqual(grounding_revision_tasks[0]["stage"], "grounding_revision")
            self.assertEqual(grounding_revision_tasks[0]["output_paths"], [str(paths["grounding"].resolve())])

    def test_final_validation_requires_v2_cognition_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            write_json(
                paths["cognition"],
                {
                    "visible_title": "Method",
                    "chart_description": "OCR and ASR summary",
                    "key_terms": ["method"],
                    "ocr_corrections": [],
                    "asr_alignment": "aligned",
                    "uncertainties": [],
                    "confidence": 0.8,
                },
            )

            result = validate_run(out, phase="final")

            self.assertFalse(result["ok"])
            self.assertTrue(any("main_claims" in error or "speaker_intent" in error for error in result["errors"]))

    def test_final_validation_requires_qa_pairs_not_fragment_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            write_json(paths["qa"], {"qa_candidates": [{"text": "base model? Oh no. My"}], "uncertainties": [], "confidence": 0.6})

            result = validate_run(out, phase="final")

            self.assertFalse(result["ok"])
            self.assertTrue(any("qa_pairs" in error for error in result["errors"]))

    def test_final_validation_requires_claim_level_grounding(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            write_json(paths["grounding"], {"grounded": True, "issues": [], "confidence": 0.8})

            result = validate_run(out, phase="final")

            self.assertFalse(result["ok"])
            self.assertTrue(any("checked_claims" in error for error in result["errors"]))

    def test_report_quality_requires_slide_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n这里有一些概括，但没有逐页 heading。\n\n"
                "## QA\n\n- Q: Did the talk explain why direct benchmark rankings disagree?\n"
                "- A: Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertFalse(result["ok"])
            self.assertTrue(any("missing slide coverage" in error for error in result["errors"]))

    def test_report_quality_rejects_long_ocr_asr_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            copied = (
                "Method train before test result ranking agreement improves across benchmarks because each model receives "
                "the same preparation before evaluation and therefore the comparison becomes less sensitive to benchmark quirks."
            )
            evidence = read_json(paths["talk_dir"] / "evidence.json")
            evidence[0]["ocr_text"] = copied
            write_json(paths["talk_dir"] / "evidence.json", evidence)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n### 第 1 张 PPT (00:00:00.000 - 00:00:30.000)\n\n"
                "![slide](../talks/talk_one/slides/slide.png)\n\n"
                f"{copied}\n\n"
                "## QA\n\n- Q: Did the talk explain why direct benchmark rankings disagree?\n"
                "- A: Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertFalse(result["ok"])
            self.assertTrue(any("copies long OCR/ASR" in error for error in result["errors"]))

    def test_final_validation_accepts_good_agent_quality_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)

            result = validate_run(out, phase="final")

            self.assertTrue(result["ok"], result)
            manifest = read_json(out / "reports_manifest.json")
            self.assertTrue(manifest["final_reports"])
            self.assertEqual(manifest["pending_reports"], [])

    def test_resume_quality_failure_enters_report_revision_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_bad_quality_outputs(paths)
            write_json(
                out / "pipeline_state.json",
                {
                    "source": "URL",
                    "completed_stages": ["ingest", "asr", "slides", "dedupe", "segment", "report", "validate"],
                    "current_status": "waiting_for_agent",
                    "blocked_gate": "report_agent",
                    "next_allowed_command": f"conference-report validate --out {out} --phase final",
                    "resume_command": f"conference-report resume --out {out}",
                    "task_manifests": ["agent_report_tasks.json", "agent_grounding_tasks.json"],
                    "human_message": "waiting",
                },
            )

            result = cli.main(["resume", "--out", str(out)])

            self.assertEqual(result, 1)
            state = read_json(out / "pipeline_state.json")
            self.assertEqual(state["blocked_gate"], "report_quality_repair")
            self.assertIn("agent_quality_repair_plan.json", state["task_manifests"])
            self.assertIn("agent_slide_cognition_revision_tasks.json", state["task_manifests"])
            self.assertIn("agent_qa_revision_tasks.json", state["task_manifests"])
            self.assertIn("agent_report_revision_tasks.json", state["task_manifests"])

    def test_final_validation_of_completed_run_marks_report_quality_repair_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_bad_quality_outputs(paths)
            write_json(
                out / "pipeline_state.json",
                {
                    "source": "URL",
                    "completed_stages": ["ingest", "asr", "slides", "dedupe", "segment", "report", "validate", "final"],
                    "current_status": "completed",
                    "blocked_gate": None,
                    "next_allowed_command": "",
                    "resume_command": "",
                    "task_manifests": [],
                    "human_message": "Pipeline completed.",
                },
            )

            result = cli.main(["validate", "--out", str(out), "--phase", "final"])

            self.assertEqual(result, 1)
            state = read_json(out / "pipeline_state.json")
            self.assertEqual(state["current_status"], "waiting_for_agent")
            self.assertEqual(state["blocked_gate"], "report_quality_repair")
            self.assertIn("agent_quality_repair_plan.json", state["task_manifests"])
            self.assertFalse(read_json(out / "reports_manifest.json")["final_reports"])

            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                status_result = cli.main(["status", "--out", str(out)])
            self.assertEqual(status_result, 0)
            status_text = stdout.getvalue()
            self.assertIn("Gate: report_quality_repair", status_text)
            self.assertIn("Failed reports: 1", status_text)
            self.assertIn("agent_slide_cognition_revision_tasks.json", status_text)
            self.assertIn("agent_qa_revision_tasks.json", status_text)
            self.assertIn("agent_report_revision_tasks.json", status_text)
            self.assertIn("agent_grounding_revision_tasks.json", status_text)

    def test_resume_report_quality_repair_completes_after_all_outputs_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_bad_quality_outputs(paths)
            cli.main(["validate", "--out", str(out), "--phase", "final"])
            state = read_json(out / "pipeline_state.json")
            self.assertEqual(state["blocked_gate"], "report_quality_repair")

            write_good_agent_outputs(paths)
            result = cli.main(["resume", "--out", str(out)])

            self.assertEqual(result, 0)
            completed = read_json(out / "pipeline_state.json")
            self.assertEqual(completed["current_status"], "completed")
            self.assertTrue(read_json(out / "reports_manifest.json")["final_reports"])


if __name__ == "__main__":
    unittest.main()
