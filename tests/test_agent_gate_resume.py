from __future__ import annotations

import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from conference_report import cli
from conference_report.config import DEFAULT_CONFIG
from conference_report.utils import read_json, write_json
from conference_report.validate import validate_run


def make_cfg():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["embeddings"]["enabled"] = True
    cfg["dedupe"]["agent_merge_confidence_threshold"] = 0.75
    return cfg


def make_slide(path: Path, color: tuple[int, int, int] = (240, 240, 240)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (320, 180), color)
    pixels = image.load()
    for x in range(40, 220):
        for y in range(50, 80):
            pixels[x, y] = (20, 20, 20)
    image.save(path)


def make_dedupe_review_task(out: Path) -> dict[str, object]:
    slide_a = out / "slides_original" / "[00:00:00.000].png"
    slide_b = out / "slides_original" / "[00:00:10.000].png"
    make_slide(slide_a)
    make_slide(slide_b, (230, 230, 230))
    candidates = [
        {
            "candidate_id": "semantic:0001",
            "slide_a_time": "00:00:00.000",
            "slide_b_time": "00:00:10.000",
            "slide_a_path": str(slide_a.resolve()),
            "slide_b_path": str(slide_b.resolve()),
            "similarity": 0.98,
            "decision": "needs_agent_review",
        }
    ]
    write_json(out / "dedupe" / "semantic_candidates.json", candidates)
    output = (out / "dedupe" / "agent_reviews" / "0001.json").resolve()
    task = {
        "task_id": "dedupe-semantic-review:0001",
        "stage": "dedupe_semantic_review",
        "candidate_id": "semantic:0001",
        "input_paths": [
            str(slide_a.resolve()),
            str(slide_b.resolve()),
            str((out / "dedupe" / "semantic_candidates.json").resolve()),
        ],
        "output_paths": [str(output)],
        "allowed_write_paths": [str(output)],
        "required_schema": {
            "same_slide": "boolean",
            "reasoning": "string",
            "confidence": "number",
        },
        "validation_rules": [
            {"type": "json_fields", "required": ["same_slide", "reasoning", "confidence"]},
            {"type": "allowed_writes"},
        ],
    }
    write_json(out / "dedupe" / "agent_review_tasks.json", [task])
    return task


def make_dedupe_rows(out: Path) -> None:
    slide_a = out / "slides_original" / "[00:00:00.000].png"
    slide_b = out / "slides_original" / "[00:00:10.000].png"
    make_slide(slide_a)
    make_slide(slide_b, (230, 230, 230))
    (out / "slides_dedup").mkdir(parents=True, exist_ok=True)
    dedup_a = out / "slides_dedup" / "[00:00:00.000].png"
    dedup_b = out / "slides_dedup" / "[00:00:10.000].png"
    dedup_a.write_bytes(slide_a.read_bytes())
    dedup_b.write_bytes(slide_b.read_bytes())
    (out / "asr").mkdir(parents=True, exist_ok=True)
    (out / "asr" / "timeline.txt").write_text(
        "[00:00:01.000] intro\n[00:00:21.000] done\n",
        encoding="utf-8",
    )
    rows = [
        {
            "cluster_id": "slide-0001",
            "time": "00:00:00.000",
            "decision": "keep",
            "kept_time": "00:00:00.000",
            "original_path": str(slide_a.resolve()),
            "kept_path": str(dedup_a.resolve()),
            "mean_abs_diff": "",
            "changed_ratio": "",
            "ahash_hamming": "",
        },
        {
            "cluster_id": "slide-0002",
            "time": "00:00:10.000",
            "decision": "keep",
            "kept_time": "00:00:10.000",
            "original_path": str(slide_b.resolve()),
            "kept_path": str(dedup_b.resolve()),
            "mean_abs_diff": "",
            "changed_ratio": "",
            "ahash_hamming": "",
        },
    ]
    write_json(out / "dedupe" / "dedup_report.json", rows)
    write_json(
        out / "dedupe_manifest.json",
        {
            "original_count": 2,
            "kept_count": 2,
            "duplicate_count": 0,
            "semantic_candidate_count": 1,
            "semantic_review_task_count": 1,
            "slides_dedup": str((out / "slides_dedup").resolve()),
        },
    )


def write_waiting_state(out: Path, gate: str) -> None:
    write_json(
        out / "pipeline_state.json",
        {
            "source": "URL",
            "completed_stages": ["ingest", "asr", "slides", "dedupe"],
            "current_status": "waiting_for_agent",
            "blocked_gate": gate,
            "next_allowed_command": f"conference-report validate --out {out} --phase {gate.replace('_', '-')}",
            "resume_command": f"conference-report resume --out {out}",
            "task_manifests": ["dedupe/agent_review_tasks.json"],
            "human_message": f"当前停在 {gate}。请完成 task manifest 后再 resume。",
        },
    )


class AgentGateResumeTests(unittest.TestCase):
    def test_build_with_dedupe_agent_gate_pauses_before_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)

            def fake_dedupe(target: Path, cfg: dict[str, object]) -> dict[str, object]:
                make_dedupe_review_task(target)
                manifest = {
                    "semantic_review_task_count": 1,
                    "semantic_candidate_count": 1,
                }
                write_json(target / "dedupe_manifest.json", manifest)
                return manifest

            with (
                mock.patch("conference_report.cli.ingest") as ingest,
                mock.patch("conference_report.cli.run_asr") as run_asr,
                mock.patch("conference_report.cli.extract_slides") as extract_slides,
                mock.patch("conference_report.cli.dedupe_slides", side_effect=fake_dedupe),
                mock.patch("conference_report.cli.segment", side_effect=AssertionError("segment must wait for dedupe gate")),
            ):
                result = cli.main(["build", "URL", "--out", str(out), "--writer", "agent", "--agent-gates", "dedupe,report"])

            self.assertEqual(result, 0)
            ingest.assert_called_once()
            run_asr.assert_called_once()
            extract_slides.assert_called_once()
            state = read_json(out / "pipeline_state.json")
            self.assertEqual(state["current_status"], "waiting_for_agent")
            self.assertEqual(state["blocked_gate"], "dedupe_review")
            self.assertIn("dedupe/agent_review_tasks.json", state["task_manifests"])
            self.assertIn("validate", state["next_allowed_command"])
            self.assertIn("resume", state["resume_command"])

    def test_segment_refuses_to_run_while_dedupe_gate_is_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_waiting_state(out, "dedupe_review")
            stdout = io.StringIO()
            with (
                mock.patch("sys.stdout", stdout),
                mock.patch("conference_report.cli.segment", side_effect=AssertionError("segment must be blocked")),
            ):
                result = cli.main(["segment", "--out", str(out)])

            self.assertEqual(result, 1)
            message = stdout.getvalue()
            self.assertIn("不能运行 segment", message)
            self.assertIn("dedupe_review", message)
            self.assertIn("validate", message)
            self.assertIn("resume", message)

    def test_validate_dedupe_review_requires_outputs_and_accepts_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            task = make_dedupe_review_task(out)

            missing = validate_run(out, phase="dedupe-review")
            self.assertFalse(missing["ok"])
            self.assertTrue(any("Missing task output" in error for error in missing["errors"]))

            output = Path(task["output_paths"][0])
            write_json(output, {"same_slide": True, "reasoning": "same layout", "confidence": 0.88})

            ok = validate_run(out, phase="dedupe-review")
            self.assertTrue(ok["ok"], ok)
            review_validation = read_json(out / "dedupe" / "agent_review_validation.json")
            self.assertTrue(review_validation["ok"])

    def test_resume_applies_high_confidence_dedupe_review(self):
        from conference_report.dedupe import apply_dedupe_agent_reviews

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            task = make_dedupe_review_task(out)
            make_dedupe_rows(out)
            write_json(Path(task["output_paths"][0]), {"same_slide": True, "reasoning": "same slide", "confidence": 0.87})

            manifest = apply_dedupe_agent_reviews(out, make_cfg())

            self.assertEqual(manifest["merged_count"], 1)
            intervals = read_json(out / "slide_intervals.json")
            self.assertEqual(len(intervals), 1)
            self.assertEqual(intervals[0]["cluster_id"], "slide-0001")
            dedupe_manifest = read_json(out / "dedupe_manifest.json")
            self.assertEqual(dedupe_manifest["kept_count"], 1)
            self.assertEqual(dedupe_manifest["duplicate_count"], 1)

    def test_resume_keeps_low_confidence_dedupe_review_separate(self):
        from conference_report.dedupe import apply_dedupe_agent_reviews

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            task = make_dedupe_review_task(out)
            make_dedupe_rows(out)
            write_json(Path(task["output_paths"][0]), {"same_slide": True, "reasoning": "uncertain", "confidence": 0.61})

            manifest = apply_dedupe_agent_reviews(out, make_cfg())

            self.assertEqual(manifest["merged_count"], 0)
            self.assertEqual(manifest["low_confidence_count"], 1)
            intervals = read_json(out / "slide_intervals.json")
            self.assertEqual(len(intervals), 2)

    def test_writer_agent_records_report_gate_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)

            def fake_generate_reports(target: Path, cfg: dict[str, object], *, writer: str | None = None, **kwargs):
                reports = target / "reports"
                reports.mkdir(parents=True, exist_ok=True)
                write_json(
                    target / "reports_manifest.json",
                    {
                        "writer_mode": "agent",
                        "final_reports": False,
                        "reports": [],
                        "planned_reports": [str((reports / "talk.md").resolve())],
                        "pending_reports": [str((reports / "talk.md").resolve())],
                        "task_manifests": {
                            "slide_cognition": str((target / "agent_slide_cognition_tasks.json").resolve()),
                            "qa_detection": str((target / "agent_qa_tasks.json").resolve()),
                            "report_write": str((target / "agent_report_tasks.json").resolve()),
                            "grounding_review": str((target / "agent_grounding_tasks.json").resolve()),
                        },
                        "task_count": 0,
                    },
                )
                for name in ["agent_slide_cognition_tasks.json", "agent_qa_tasks.json", "agent_report_tasks.json", "agent_grounding_tasks.json"]:
                    write_json(target / name, [])
                return [reports / "talk.md"]

            with (
                mock.patch("conference_report.cli.ingest"),
                mock.patch("conference_report.cli.run_asr"),
                mock.patch("conference_report.cli.extract_slides"),
                mock.patch("conference_report.cli.dedupe_slides", return_value={"semantic_review_task_count": 0}),
                mock.patch("conference_report.cli.segment"),
                mock.patch("conference_report.cli.generate_reports", side_effect=fake_generate_reports),
                mock.patch("conference_report.cli.validate_run", return_value={"ok": True}),
            ):
                result = cli.main(["build", "URL", "--out", str(out), "--writer", "agent"])

            self.assertEqual(result, 0)
            state = read_json(out / "pipeline_state.json")
            self.assertEqual(state["current_status"], "waiting_for_agent")
            self.assertEqual(state["blocked_gate"], "report_agent")
            self.assertIn("agent_report_tasks.json", state["task_manifests"])
            self.assertIn("--phase final", state["next_allowed_command"])

    def test_status_outputs_current_gate_and_next_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_waiting_state(out, "dedupe_review")
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                result = cli.main(["status", "--out", str(out)])

            self.assertEqual(result, 0)
            text = stdout.getvalue()
            self.assertIn("waiting_for_agent", text)
            self.assertIn("dedupe_review", text)
            self.assertIn("Next:", text)


if __name__ == "__main__":
    unittest.main()
