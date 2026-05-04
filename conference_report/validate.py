from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .utils import read_json, timeline_lines, write_json


VALIDATION_PHASES = {"evidence", "agent-tasks", "final"}
TASK_MANIFESTS = {
    "slide_cognition": "agent_slide_cognition_tasks.json",
    "qa_detection": "agent_qa_tasks.json",
    "report_write": "agent_report_tasks.json",
    "grounding_review": "agent_grounding_tasks.json",
}
TASK_REQUIRED_KEYS = {"task_id", "stage", "input_paths", "output_paths", "allowed_write_paths", "validation_rules"}
REPORT_REQUIRED_SECTIONS = ["摘要", "核心 Findings / Experiments / Insights", "逐页 PPT 解读", "QA"]


def normalize_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def markdown_image_errors(report: Path) -> list[str]:
    errors: list[str] = []
    text = report.read_text(encoding="utf-8", errors="ignore")
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
        raw_link = unquote(match.group(1)).split("#", 1)[0]
        if "://" in raw_link:
            continue
        image = (report.parent / raw_link).resolve()
        if not image.exists():
            errors.append(f"Broken image in {report.name}: {match.group(1)}")
    return errors


def missing_markdown_sections(report: Path, sections: list[str]) -> list[str]:
    text = report.read_text(encoding="utf-8", errors="ignore")
    headings = [match.group(1).strip() for match in re.finditer(r"^#{1,6}\s+(.+)$", text, flags=re.MULTILINE)]
    missing: list[str] = []
    for section in sections:
        if not any(section in heading for heading in headings):
            missing.append(section)
    return missing


def validate_json_schema(path: Path, stage: str) -> list[str]:
    errors: list[str] = []
    try:
        data = read_json(path)
    except Exception as exc:
        return [f"Invalid JSON task output {path}: {exc}"]
    if stage == "slide_cognition":
        required = {
            "visible_title": str,
            "chart_description": str,
            "key_terms": list,
            "ocr_corrections": list,
            "asr_alignment": str,
            "uncertainties": list,
            "confidence": (int, float),
        }
    elif stage == "qa_detection":
        required = {"qa_candidates": list, "uncertainties": list, "confidence": (int, float)}
    elif stage == "grounding_review":
        required = {"grounded": bool, "issues": list, "confidence": (int, float)}
    else:
        return errors
    for key, expected_type in required.items():
        if key not in data:
            errors.append(f"Missing required JSON field {key} in {path}")
        elif not isinstance(data[key], expected_type):
            errors.append(f"Invalid JSON field {key} in {path}")
    return errors


def load_task_manifests(out_dir: Path, errors: list[str], *, expect_agent: bool) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for stage, filename in TASK_MANIFESTS.items():
        path = out_dir / filename
        if not path.exists():
            if expect_agent:
                errors.append(f"Missing {filename}")
            continue
        try:
            loaded = read_json(path)
        except Exception as exc:
            errors.append(f"Invalid {filename}: {exc}")
            continue
        if not isinstance(loaded, list):
            errors.append(f"{filename} must be a list")
            continue
        for task in loaded:
            if isinstance(task, dict):
                task["_manifest_path"] = str(path.resolve())
                tasks.append(task)
            else:
                errors.append(f"{filename} contains a non-object task")
    return tasks


def validate_task_contract(task: dict[str, Any], *, final: bool) -> dict[str, Any]:
    task_errors: list[str] = []
    task_id = str(task.get("task_id", "<missing>"))
    stage = str(task.get("stage", "<missing>"))
    missing_keys = sorted(TASK_REQUIRED_KEYS - task.keys())
    for key in missing_keys:
        task_errors.append(f"Task {task_id} missing required key {key}")
    output_paths = [normalize_path(path) for path in task.get("output_paths", []) if isinstance(path, str)]
    allowed_paths = {normalize_path(path) for path in task.get("allowed_write_paths", []) if isinstance(path, str)}
    input_paths = [normalize_path(path) for path in task.get("input_paths", []) if isinstance(path, str)]
    dependency_paths = [normalize_path(path) for path in task.get("dependency_output_paths", []) if isinstance(path, str)]
    for output in output_paths:
        if output not in allowed_paths:
            task_errors.append(f"Task {task_id} output {output} is not listed in allowed_write_paths")
    for input_path in input_paths:
        if not Path(input_path).exists():
            task_errors.append(f"Task {task_id} input path does not exist: {input_path}")
    if final:
        for dependency in dependency_paths:
            if not Path(dependency).exists():
                task_errors.append(f"Task {task_id} dependency output is missing: {dependency}")
        for output in output_paths:
            output_path = Path(output)
            if not output_path.exists():
                task_errors.append(f"Missing task output for {task_id}: {output}")
                continue
            if stage == "report_write":
                for section in task.get("required_sections", []):
                    if section in missing_markdown_sections(output_path, [str(section)]):
                        task_errors.append(f"Missing required section {section} in {output}")
                task_errors.extend(markdown_image_errors(output_path))
            else:
                task_errors.extend(validate_json_schema(output_path, stage))
    return {"task_id": task_id, "stage": stage, "ok": not task_errors, "errors": task_errors}


def validate_agent_tasks(out_dir: Path, *, phase: str, errors: list[str]) -> dict[str, Any]:
    initial_error_count = len(errors)
    reports_manifest = read_json(out_dir / "reports_manifest.json") if (out_dir / "reports_manifest.json").exists() else {}
    expect_agent = reports_manifest.get("writer_mode") == "agent"
    tasks = load_task_manifests(out_dir, errors, expect_agent=expect_agent)
    final = phase == "final"
    task_results = [validate_task_contract(task, final=final) for task in tasks]
    for result in task_results:
        errors.extend(result["errors"])
    if final and expect_agent:
        completed_reports: list[str] = []
        pending_reports: list[str] = []
        for report in reports_manifest.get("planned_reports", []):
            if not Path(report).exists():
                errors.append(f"Missing planned report: {report}")
                pending_reports.append(report)
            else:
                completed_reports.append(report)
        for report in reports_manifest.get("reports", []):
            if not Path(report).exists():
                errors.append(f"reports_manifest lists missing report: {report}")
        reports_manifest["completed_reports"] = completed_reports
        reports_manifest["pending_reports"] = pending_reports
        reports_manifest["reports"] = completed_reports
    if final and reports_manifest.get("writer_mode") == "openai":
        for report in reports_manifest.get("planned_reports", reports_manifest.get("reports", [])):
            report_path = Path(report)
            if not report_path.exists():
                errors.append(f"Missing planned report: {report}")
                continue
            for section in missing_markdown_sections(report_path, REPORT_REQUIRED_SECTIONS):
                errors.append(f"Missing required section {section} in {report}")
    local_errors = errors[initial_error_count:]
    ok = not local_errors and not any(not item["ok"] for item in task_results)
    if final and expect_agent:
        reports_manifest["final_reports"] = ok and not reports_manifest.get("pending_reports")
        write_json(out_dir / "reports_manifest.json", reports_manifest)
    result = {"ok": ok, "phase": phase, "manifest_errors": local_errors, "tasks": task_results}
    write_json(out_dir / "agent_task_validation.json", result)
    return result


def validate_evidence(out_dir: Path, errors: list[str], warnings: list[str]) -> None:
    timeline = out_dir / "asr" / "timeline.txt"
    if not timeline.exists():
        errors.append("Missing asr/timeline.txt")
    else:
        rows = timeline_lines(timeline)
        if not rows:
            errors.append("ASR timeline is empty")
        if any(rows[i]["seconds"] > rows[i + 1]["seconds"] for i in range(len(rows) - 1)):
            errors.append("ASR timeline is not monotonic")

    for required in ["slides_original", "slides_dedup", "slide_intervals.json", "segmentation/talks.json"]:
        if not (out_dir / required).exists():
            errors.append(f"Missing {required}")

    if (out_dir / "slide_intervals.json").exists():
        intervals = read_json(out_dir / "slide_intervals.json")
        if any(item["start_seconds"] > item["end_seconds"] for item in intervals):
            errors.append("Slide interval has start > end")

    if (out_dir / "segmentation" / "talks.json").exists():
        talks = read_json(out_dir / "segmentation" / "talks.json")
        for talk in talks:
            if talk.get("reportable"):
                if not talk.get("slug"):
                    errors.append(f"Reportable talk missing slug: {talk.get('talk_id')}")
                elif not (out_dir / "talks" / talk["slug"]).exists():
                    warnings.append(f"Reportable talk not packaged: {talk.get('talk_id')}")


def validate_existing_report_links(out_dir: Path, warnings: list[str], *, strict: bool, errors: list[str]) -> None:
    for report in (out_dir / "reports").glob("*.md") if (out_dir / "reports").exists() else []:
        link_errors = markdown_image_errors(report)
        if strict:
            errors.extend(link_errors)
        else:
            warnings.extend(link_errors)


def validate_run(out_dir: Path, phase: str = "evidence") -> dict[str, Any]:
    if phase not in VALIDATION_PHASES:
        raise ValueError(f"Unsupported validation phase: {phase}")
    errors: list[str] = []
    warnings: list[str] = []

    validate_evidence(out_dir, errors, warnings)
    if phase in {"agent-tasks", "final"}:
        validate_agent_tasks(out_dir, phase=phase, errors=errors)
    validate_existing_report_links(out_dir, warnings, strict=phase == "final", errors=errors)

    result = {"ok": not errors, "phase": phase, "errors": errors, "warnings": warnings}
    write_json(out_dir / "validation.json", result)
    return result
