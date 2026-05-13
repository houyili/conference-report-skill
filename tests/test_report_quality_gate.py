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
    provenance = talk_dir / "agent_execution" / "report_writer_provenance.json"
    for path in [cognition, qa, provenance]:
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
                "allowed_write_paths": [str(report.resolve()), str(provenance.resolve())],
                "execution_provenance_path": str(provenance.resolve()),
                "requires_subagent": True,
                "required_provenance": {
                    "path": str(provenance.resolve()),
                    "worker_type": "subagent",
                    "isolation_scope": "single_report",
                },
                "required_sections": ["摘要", "核心 Findings / Experiments / Insights", "逐页 PPT 解读", "QA"],
                "validation_rules": [
                    {"type": "exists"},
                    {"type": "markdown_required_sections"},
                    {"type": "execution_provenance", "worker_type": "subagent", "isolation_scope": "single_report"},
                    {"type": "allowed_writes"},
                ],
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
    return {"talk_dir": talk_dir, "slide": slide, "report": report, "grounding": grounding, "cognition": cognition, "qa": qa, "provenance": provenance}


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
    write_json(
        paths["provenance"],
        {
            "host_agent_framework": "codex",
            "worker_type": "subagent",
            "worker_id": "quality-test-worker",
            "isolation_scope": "single_report",
            "assigned_task_id": f"report:{paths['report'].stem}",
            "assigned_slug": paths["report"].stem,
            "topic_understanding_confirmed": True,
            "input_paths_read": [
                str((paths["talk_dir"] / "evidence.json").resolve()),
                str((paths["talk_dir"] / "metadata.json").resolve()),
                str((paths["talk_dir"] / "timeline.txt").resolve()),
                str((paths["talk_dir"] / "slides").resolve()),
                str(paths["cognition"].resolve()),
                str(paths["qa"].resolve()),
            ],
            "output_paths_written": [str(paths["report"].resolve()), str(paths["provenance"].resolve())],
            "allowed_write_paths": [str(paths["report"].resolve()), str(paths["provenance"].resolve())],
        },
    )


def enable_talk_synthesis_requirement(paths: dict[str, Path]) -> Path:
    synthesis = paths["talk_dir"] / "talk_synthesis.md"
    report_tasks = read_json(paths["talk_dir"].parents[1] / "agent_report_tasks.json")
    task = report_tasks[0]
    task["synthesis_path"] = str(synthesis.resolve())
    task["intermediate_output_paths"] = [str(synthesis.resolve())]
    if str(synthesis.resolve()) not in task["allowed_write_paths"]:
        task["allowed_write_paths"].append(str(synthesis.resolve()))
    task["validation_rules"].append({"type": "talk_synthesis"})
    write_json(paths["talk_dir"].parents[1] / "agent_report_tasks.json", report_tasks)
    return synthesis


def write_good_talk_synthesis(paths: dict[str, Path], synthesis: Path) -> None:
    synthesis.write_text(
        "# Talk synthesis\n\n"
        "## Core question / 核心问题\n\n"
        "The talk asks whether identical benchmark-specific preparation makes model ranking comparisons more reliable.\n\n"
        "## Method / 方法\n\n"
        "Each model is prepared on the benchmark training split before the held-out test comparison.\n\n"
        "## Result / 结果\n\n"
        "The key finding is stronger ranking agreement across benchmarks after train-before-test.\n\n"
        "## Slide role map\n\n"
        "- Slide 1 introduces the comparison method and result; no slide is evidence-only in this fixture.\n",
        encoding="utf-8",
    )
    provenance = read_json(paths["provenance"])
    provenance["output_paths_written"].append(str(synthesis.resolve()))
    provenance["allowed_write_paths"].append(str(synthesis.resolve()))
    write_json(paths["provenance"], provenance)


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
    write_json(
        paths["provenance"],
        {
            "host_agent_framework": "codex",
            "worker_type": "subagent",
            "worker_id": "quality-test-worker",
            "isolation_scope": "single_report",
            "assigned_task_id": f"report:{paths['report'].stem}",
            "assigned_slug": paths["report"].stem,
            "topic_understanding_confirmed": True,
            "input_paths_read": [
                str((paths["talk_dir"] / "evidence.json").resolve()),
                str((paths["talk_dir"] / "metadata.json").resolve()),
                str((paths["talk_dir"] / "timeline.txt").resolve()),
                str((paths["talk_dir"] / "slides").resolve()),
                str(paths["cognition"].resolve()),
                str(paths["qa"].resolve()),
            ],
            "output_paths_written": [str(paths["report"].resolve()), str(paths["provenance"].resolve())],
            "allowed_write_paths": [str(paths["report"].resolve()), str(paths["provenance"].resolve())],
        },
    )


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
            self.assertEqual(repair_plan["active_stages"], repair_plan["stages"])
            self.assertIn("agent_slide_cognition_revision_tasks.json", repair_plan["task_manifests"].values())
            self.assertIn("agent_qa_revision_tasks.json", repair_plan["task_manifests"].values())
            self.assertIn("agent_report_revision_tasks.json", repair_plan["task_manifests"].values())
            self.assertIn("agent_grounding_revision_tasks.json", repair_plan["task_manifests"].values())

            cognition_tasks = read_json(out / "agent_slide_cognition_revision_tasks.json")
            self.assertEqual([task["stage"] for task in cognition_tasks], ["slide_cognition_revision"])
            self.assertEqual(cognition_tasks[0]["prompt_contract"]["parent_sequential_ok"], True)
            self.assertEqual(cognition_tasks[0]["output_paths"], [str(paths["cognition"].resolve())])
            self.assertEqual(cognition_tasks[0]["allowed_write_paths"], cognition_tasks[0]["output_paths"])

            qa_revision_tasks = read_json(out / "agent_qa_revision_tasks.json")
            self.assertEqual(qa_revision_tasks[0]["stage"], "qa_revision")
            self.assertEqual(qa_revision_tasks[0]["output_paths"], [str(paths["qa"].resolve())])
            self.assertEqual(qa_revision_tasks[0]["allowed_write_paths"], qa_revision_tasks[0]["output_paths"])

            report_revision_tasks = read_json(out / "agent_report_revision_tasks.json")
            self.assertEqual(report_revision_tasks[0]["stage"], "report_revision")
            self.assertEqual(report_revision_tasks[0]["output_paths"], [str(paths["report"].resolve())])
            self.assertEqual(report_revision_tasks[0]["execution_provenance_path"], str(paths["provenance"].resolve()))
            self.assertEqual(report_revision_tasks[0]["original_report_task_id"], f"report:{paths['report'].stem}")
            self.assertEqual(
                report_revision_tasks[0]["provenance_assignment"]["assigned_task_id"],
                f"report:{paths['report'].stem}",
            )
            self.assertIn("not this report-revision task id", report_revision_tasks[0]["done_condition"])
            self.assertIn(str(paths["provenance"].resolve()), report_revision_tasks[0]["allowed_write_paths"])
            self.assertTrue(report_revision_tasks[0]["requires_subagent"])
            self.assertTrue(report_revision_tasks[0]["prompt_contract"]["requires_subagent"])

            grounding_revision_tasks = read_json(out / "agent_grounding_revision_tasks.json")
            self.assertEqual(grounding_revision_tasks[0]["stage"], "grounding_revision")
            self.assertEqual(grounding_revision_tasks[0]["output_paths"], [str(paths["grounding"].resolve())])
            execution_plan = read_json(out / "agent_execution_plan.json")
            self.assertEqual(
                [group["stage"] for group in execution_plan["repair_worker_groups"]],
                ["slide_cognition_revision", "qa_revision", "report_revision", "grounding_revision"],
            )

    def test_report_revision_task_infers_provenance_path_for_legacy_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_bad_quality_outputs(paths)
            report_tasks = read_json(out / "agent_report_tasks.json")
            del report_tasks[0]["execution_provenance_path"]
            del report_tasks[0]["required_provenance"]
            del report_tasks[0]["requires_subagent"]
            report_tasks[0]["allowed_write_paths"] = [str(paths["report"].resolve())]
            write_json(out / "agent_report_tasks.json", report_tasks)

            result = validate_run(out, phase="report-quality")

            self.assertFalse(result["ok"])
            report_revision_tasks = read_json(out / "agent_report_revision_tasks.json")
            self.assertEqual(report_revision_tasks[0]["execution_provenance_path"], str(paths["provenance"].resolve()))
            self.assertIn(str(paths["provenance"].resolve()), report_revision_tasks[0]["allowed_write_paths"])

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

    def test_report_quality_accepts_slide_coverage_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n"
                "### Slide 1 (00:00:00.000 - 00:00:30.000)\n\n"
                "![slide](../talks/talk_one/slides/slide.png)\n\n"
                "This slide explains train-before-test as a comparison method and uses identical preparation to make model rankings more comparable.\n\n"
                "## QA\n\n- Q: Did the talk explain why direct benchmark rankings disagree?\n"
                "- A: Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertTrue(result["ok"], result)
            metrics = read_json(out / "report_quality_validation.json")["reports"][0]["metrics"]
            self.assertEqual(metrics["covered_slide_count"], 1)

    def test_report_quality_accepts_angle_bracket_image_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n"
                "### 第 1 张 PPT (00:00:00.000 - 00:00:30.000)\n\n"
                "![slide](<../talks/talk_one/slides/slide.png>)\n\n"
                "This slide explains train-before-test as a comparison method and uses identical preparation to make model rankings more comparable.\n\n"
                "## QA\n\n- Q: Did the talk explain why direct benchmark rankings disagree?\n"
                "- A: Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertTrue(result["ok"], result)

    def test_report_quality_accepts_qa_pair_paraphrase_with_key_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n"
                "### 第 1 张 PPT (00:00:00.000 - 00:00:30.000)\n\n"
                "![slide](../talks/talk_one/slides/slide.png)\n\n"
                "This slide explains train-before-test as a comparison method and uses identical preparation to make model rankings more comparable.\n\n"
                "## QA\n\n"
                "- qa_pairs 对齐摘要：提问围绕 direct benchmark rankings disagreement；回答指出 unequal benchmark-specific preparation before evaluation 是一个主要原因。\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertTrue(result["ok"], result)

    def test_report_quality_accepts_original_slide_index_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            evidence = read_json(paths["talk_dir"] / "evidence.json")
            evidence[0]["slide_index"] = "9"
            write_json(paths["talk_dir"] / "evidence.json", evidence)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n"
                "### Slide 9 (00:00:00.000 - 00:00:30.000)\n\n"
                "![slide](../talks/talk_one/slides/slide.png)\n\n"
                "This slide explains train-before-test as a comparison method and uses identical preparation to make model rankings more comparable.\n\n"
                "## QA\n\n- Q: Did the talk explain why direct benchmark rankings disagree?\n"
                "- A: Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertTrue(result["ok"], result)

    def test_report_quality_ignores_evidence_only_slides_for_main_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            evidence = read_json(paths["talk_dir"] / "evidence.json")
            evidence.append(
                {
                    "slide_index": "2",
                    "time": "00:00:31.000 - 00:00:40.000",
                    "image": str(paths["slide"].resolve()),
                    "ocr_text": "Conference transition screen",
                    "asr_text": "The chair introduces the next speaker.",
                    "role": "标题或过渡页",
                    "evidence_only": True,
                }
            )
            write_json(paths["talk_dir"] / "evidence.json", evidence)

            result = validate_run(out, phase="report-quality")

            self.assertTrue(result["ok"], result)
            metrics = read_json(out / "report_quality_validation.json")["reports"][0]["metrics"]
            self.assertEqual(metrics["expected_slide_count"], 1)
            self.assertEqual(metrics["evidence_only_count"], 1)

    def test_report_quality_rejects_reader_visible_audit_scaffolding(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n"
                "### 第 1 张 | Slide 1 | slide_index: 1 | 00:00:00.000 - 00:00:30.000\n\n"
                "slide_index: 1\n\n"
                "![slide](../talks/talk_one/slides/slide.png)\n\n"
                "证据源为 evidence.json 第 1 条，原始 PPT slide_index 为 1。这页说明 train-before-test 会让模型排名更可比较。\n\n"
                "## QA\n\n- Q: Did the talk explain why direct benchmark rankings disagree?\n"
                "- A: Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertFalse(result["ok"])
            quality = read_json(out / "report_quality_validation.json")
            self.assertIn("scaffolding", quality["reports"][0]["quality_issue_classes"])
            self.assertTrue(any("audit scaffolding" in error for error in quality["reports"][0]["errors"]))

    def test_report_quality_classifies_qa_usage_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n### 第 1 张 PPT (00:00:00.000 - 00:00:30.000)\n\n"
                "![slide](../talks/talk_one/slides/slide.png)\n\n"
                "这页提出 train-before-test，并说明 identical preparation before testing makes language model rankings more comparable。\n\n"
                "## QA\n\n未检测到可靠问答。\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertFalse(result["ok"])
            quality = read_json(out / "report_quality_validation.json")
            self.assertIn("qa_usage", quality["reports"][0]["quality_issue_classes"])

    def test_report_quality_rejects_repeated_slide_index_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            evidence = read_json(paths["talk_dir"] / "evidence.json")
            for idx in [2, 3, 4]:
                slide = paths["talk_dir"] / "slide_cognition" / f"{idx:04d}.json"
                slide.parent.mkdir(parents=True, exist_ok=True)
                slide.write_text(paths["cognition"].read_text(encoding="utf-8"), encoding="utf-8")
                evidence.append(
                    {
                        "slide_index": str(idx),
                        "time": f"00:00:{idx * 10:02d}.000 - 00:00:{idx * 10 + 5:02d}.000",
                        "image": str(paths["slide"].resolve()),
                        "ocr_text": "Method: train-before-test. Result: ranking agreement improves across benchmarks.",
                        "asr_text": "The slide explains a method for comparing model rankings after identical preparation.",
                        "role": "方法页",
                    }
                )
            write_json(paths["talk_dir"] / "evidence.json", evidence)
            cognition_tasks = read_json(out / "agent_slide_cognition_tasks.json")
            for idx in [2, 3, 4]:
                path = paths["talk_dir"] / "slide_cognition" / f"{idx:04d}.json"
                cognition_tasks.append({**cognition_tasks[0], "task_id": f"slide-cognition:talk_one:{idx:04d}", "slide_index": idx, "output_paths": [str(path.resolve())], "allowed_write_paths": [str(path.resolve())]})
            write_json(out / "agent_slide_cognition_tasks.json", cognition_tasks)
            sections = []
            for idx in [1, 2, 3, 4]:
                sections.append(
                    f"### 第 {idx} 张 PPT\n\nslide_index: {idx}\n\n![slide](../talks/talk_one/slides/slide.png)\n\n"
                    "This slide explains train-before-test as a comparison method and uses identical preparation to make model rankings more comparable.\n"
                )
            paths["report"].write_text(
                "# Talk One\n\n"
                "## 摘要\n\n这场 talk 讨论 train-before-test 的比较协议。\n\n"
                "## 核心 Findings / Experiments / Insights\n\n- Identical preparation before testing makes language model rankings more comparable.\n\n"
                "## 逐页 PPT 解读\n\n"
                + "\n".join(sections)
                + "\n## QA\n\n- Q: Did the talk explain why direct benchmark rankings disagree?\n"
                "- A: Yes. The speaker attributes disagreement partly to unequal benchmark-specific preparation before evaluation.\n",
                encoding="utf-8",
            )

            result = validate_run(out, phase="report-quality")

            self.assertFalse(result["ok"])
            self.assertTrue(any("standalone slide_index" in error or "slide_index metadata" in error for error in result["errors"]))

    def test_report_quality_requires_talk_synthesis_when_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            synthesis = enable_talk_synthesis_requirement(paths)

            result = validate_run(out, phase="final")

            self.assertFalse(result["ok"])
            self.assertTrue(any("talk synthesis" in error.lower() for error in result["errors"]))
            report_revision_tasks = read_json(out / "agent_report_revision_tasks.json")
            self.assertEqual(report_revision_tasks[0]["intermediate_output_paths"], [str(synthesis.resolve())])
            self.assertIn(str(synthesis.resolve()), report_revision_tasks[0]["allowed_write_paths"])
            self.assertEqual(report_revision_tasks[0]["synthesis_path"], str(synthesis.resolve()))
            self.assertIn({"type": "talk_synthesis"}, report_revision_tasks[0]["validation_rules"])

    def test_report_quality_accepts_declared_talk_synthesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            paths = make_agent_quality_run(out)
            write_good_agent_outputs(paths)
            synthesis = enable_talk_synthesis_requirement(paths)
            write_good_talk_synthesis(paths, synthesis)

            result = validate_run(out, phase="final")

            self.assertTrue(result["ok"], result)

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
            repair_plan = read_json(out / "agent_quality_repair_plan.json")
            self.assertTrue(repair_plan["resolved"])
            self.assertIsNone(repair_plan["blocked_gate"])
            self.assertEqual(repair_plan["failed_reports"], [])
            self.assertEqual(repair_plan["active_stages"], [])
            self.assertIn("historical_failed_reports", repair_plan)


if __name__ == "__main__":
    unittest.main()
