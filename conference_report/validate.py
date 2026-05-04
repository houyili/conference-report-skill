from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .utils import read_json, timeline_lines, write_json


VALIDATION_PHASES = {"evidence", "dedupe-review", "agent-tasks", "report-quality", "final"}
TASK_MANIFESTS = {
    "slide_cognition": "agent_slide_cognition_tasks.json",
    "qa_detection": "agent_qa_tasks.json",
    "report_write": "agent_report_tasks.json",
    "grounding_review": "agent_grounding_tasks.json",
}
TASK_REQUIRED_KEYS = {"task_id", "stage", "input_paths", "output_paths", "allowed_write_paths", "validation_rules"}
REPORT_REQUIRED_SECTIONS = ["摘要", "核心 Findings / Experiments / Insights", "逐页 PPT 解读", "QA"]
DEDUPE_REVIEW_TASK_MANIFEST = "dedupe/agent_review_tasks.json"
REPORT_QUALITY_FILE = "report_quality_validation.json"
QUALITY_REPAIR_PLAN_FILE = "agent_quality_repair_plan.json"
SLIDE_COGNITION_REVISION_TASKS_FILE = "agent_slide_cognition_revision_tasks.json"
QA_REVISION_TASKS_FILE = "agent_qa_revision_tasks.json"
REVISION_TASKS_FILE = "agent_report_revision_tasks.json"
GROUNDING_REVISION_TASKS_FILE = "agent_grounding_revision_tasks.json"

QUALITY_REPAIR_STAGES = [
    "slide_cognition_revision",
    "qa_revision",
    "report_revision",
    "grounding_revision",
]
QUALITY_REPAIR_MANIFESTS = {
    "slide_cognition_revision": SLIDE_COGNITION_REVISION_TASKS_FILE,
    "qa_revision": QA_REVISION_TASKS_FILE,
    "report_revision": REVISION_TASKS_FILE,
    "grounding_revision": GROUNDING_REVISION_TASKS_FILE,
}


TEMPLATE_PHRASES = [
    "综合来看，这页的作用是把可见 PPT 内容和讲者说明对齐起来",
    "支撑本 talk 的问题动机、方法、实验或结论之一",
    "若 OCR/ASR 有误，应以截图中的可见文字为优先依据",
    "这页在报告结构中更像是",
]

V2_SLIDE_COGNITION_FIELDS = {
    "visual_summary",
    "speaker_intent",
    "main_claims",
    "method_details",
    "experiment_or_result",
    "numbers_and_entities",
    "asr_corrections",
    "uncertainties",
    "confidence",
}

V2_QA_FIELDS = {"qa_pairs", "uncertainties", "confidence"}
V2_GROUNDING_FIELDS = {
    "checked_claims",
    "unsupported_claims",
    "missing_coverage",
    "template_or_style_issues",
    "requires_revision",
    "confidence",
}

V2_SLIDE_COGNITION_SCHEMA = {
    "visual_summary": "string",
    "speaker_intent": "string",
    "main_claims": "array",
    "method_details": "array",
    "experiment_or_result": "array",
    "numbers_and_entities": "array",
    "asr_corrections": "array",
    "uncertainties": "array",
    "confidence": "number",
}
V2_QA_SCHEMA = {"qa_pairs": "array", "uncertainties": "array", "confidence": "number"}
V2_GROUNDING_SCHEMA = {
    "checked_claims": "array",
    "unsupported_claims": "array",
    "missing_coverage": "array",
    "template_or_style_issues": "array",
    "requires_revision": "boolean",
    "confidence": "number",
}


JSON_SCHEMA_TYPES = {
    "string": str,
    "array": list,
    "number": (int, float),
    "boolean": bool,
}


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
            "visual_summary": str,
            "speaker_intent": str,
            "main_claims": list,
            "method_details": list,
            "experiment_or_result": list,
            "numbers_and_entities": list,
            "asr_corrections": list,
            "uncertainties": list,
            "confidence": (int, float),
        }
    elif stage == "qa_detection":
        required = {"qa_pairs": list, "uncertainties": list, "confidence": (int, float)}
    elif stage == "grounding_review":
        required = {
            "checked_claims": list,
            "unsupported_claims": list,
            "missing_coverage": list,
            "template_or_style_issues": list,
            "requires_revision": bool,
            "confidence": (int, float),
        }
    else:
        return errors
    for key, expected_type in required.items():
        if key not in data:
            errors.append(f"Missing required JSON field {key} in {path}")
        elif not isinstance(data[key], expected_type):
            errors.append(f"Invalid JSON field {key} in {path}")
    return errors


def validate_declared_json_schema(path: Path, schema: dict[str, str]) -> list[str]:
    errors: list[str] = []
    try:
        data = read_json(path)
    except Exception as exc:
        return [f"Invalid JSON task output {path}: {exc}"]
    for key, expected_name in schema.items():
        expected_type = JSON_SCHEMA_TYPES.get(str(expected_name))
        if expected_type is None:
            continue
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
            elif isinstance(task.get("required_schema"), dict):
                task_errors.extend(validate_declared_json_schema(output_path, task["required_schema"]))
            else:
                task_errors.extend(validate_json_schema(output_path, stage))
    return {"task_id": task_id, "stage": stage, "ok": not task_errors, "errors": task_errors}


def validate_dedupe_review_tasks(out_dir: Path, errors: list[str]) -> dict[str, Any]:
    manifest_path = out_dir / DEDUPE_REVIEW_TASK_MANIFEST
    if not manifest_path.exists():
        errors.append(f"Missing {DEDUPE_REVIEW_TASK_MANIFEST}")
        result = {"ok": False, "phase": "dedupe-review", "tasks": [], "manifest_errors": errors[:]}
        write_json(out_dir / "dedupe" / "agent_review_validation.json", result)
        return result
    try:
        tasks = read_json(manifest_path)
    except Exception as exc:
        errors.append(f"Invalid {DEDUPE_REVIEW_TASK_MANIFEST}: {exc}")
        tasks = []
    if not isinstance(tasks, list):
        errors.append(f"{DEDUPE_REVIEW_TASK_MANIFEST} must be a list")
        tasks = []
    task_results = [validate_task_contract(task, final=True) for task in tasks if isinstance(task, dict)]
    for task in tasks:
        if not isinstance(task, dict):
            errors.append(f"{DEDUPE_REVIEW_TASK_MANIFEST} contains a non-object task")
    for result in task_results:
        errors.extend(result["errors"])
    result = {
        "ok": not errors and all(item["ok"] for item in task_results),
        "phase": "dedupe-review",
        "tasks": task_results,
        "manifest_errors": errors[:],
    }
    write_json(out_dir / "dedupe" / "agent_review_validation.json", result)
    return result


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


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def sentence_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sentence in re.split(r"[。！？.!?\n]+", text):
        normalized = normalize_text(sentence)
        if len(normalized) < 28:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    return counts


def task_output(task: dict[str, Any]) -> Path | None:
    outputs = task.get("output_paths") or []
    if not outputs:
        return None
    return Path(str(outputs[0]))


def tasks_by_stage_and_slug(out_dir: Path, errors: list[str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    tasks = load_task_manifests(out_dir, errors, expect_agent=True)
    for task in tasks:
        stage = str(task.get("stage", ""))
        slug = str(task.get("slug", ""))
        if not slug:
            continue
        grouped.setdefault(stage, {}).setdefault(slug, []).append(task)
    return grouped


def validate_cognition_quality(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = read_json(path)
    except Exception as exc:
        return [f"Invalid slide cognition JSON {path}: {exc}"]
    missing = sorted(V2_SLIDE_COGNITION_FIELDS - set(data))
    errors.extend(f"Missing v2 slide cognition field {field} in {path}" for field in missing)
    if missing:
        return errors
    if len(str(data.get("visual_summary", "")).strip()) < 30:
        errors.append(f"slide cognition visual_summary is too shallow in {path}")
    if len(str(data.get("speaker_intent", "")).strip()) < 30:
        errors.append(f"slide cognition speaker_intent is too shallow in {path}")
    if not data.get("main_claims"):
        errors.append(f"slide cognition main_claims is empty in {path}")
    shallow_markers = ["该页可见内容主要是", "对应 ASR 说明", "OCR and ASR summary"]
    combined = f"{data.get('visual_summary', '')} {data.get('speaker_intent', '')}"
    if any(marker in combined for marker in shallow_markers):
        errors.append(f"slide cognition appears to copy OCR/ASR instead of explaining the slide in {path}")
    return errors


def validate_qa_quality(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = read_json(path)
    except Exception as exc:
        return [f"Invalid QA JSON {path}: {exc}"]
    missing = sorted(V2_QA_FIELDS - set(data))
    errors.extend(f"Missing v2 QA field {field} in {path}" for field in missing)
    if missing:
        return errors
    qa_pairs = data.get("qa_pairs") or []
    if not isinstance(qa_pairs, list):
        return [f"qa_pairs must be an array in {path}"]
    required_pair_fields = {"question", "answer", "time_range", "evidence_quotes", "confidence"}
    for idx, pair in enumerate(qa_pairs, start=1):
        if not isinstance(pair, dict):
            errors.append(f"qa_pairs[{idx}] must be an object in {path}")
            continue
        pair_missing = sorted(required_pair_fields - set(pair))
        errors.extend(f"qa_pairs[{idx}] missing {field} in {path}" for field in pair_missing)
        if len(str(pair.get("question", "")).strip()) < 12:
            errors.append(f"qa_pairs[{idx}] question is too short in {path}")
        if len(str(pair.get("answer", "")).strip()) < 12:
            errors.append(f"qa_pairs[{idx}] answer is too short in {path}")
    if not qa_pairs:
        uncertainty_text = " ".join(str(item) for item in data.get("uncertainties", []))
        if not any(marker in uncertainty_text.lower() for marker in ["no reliable", "未能可靠", "没有可靠", "未检测到"]):
            errors.append(f"qa_pairs is empty without a no-reliable-QA uncertainty in {path}")
    return errors


def validate_grounding_quality(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = read_json(path)
    except Exception as exc:
        return [f"Invalid grounding JSON {path}: {exc}"]
    missing = sorted(V2_GROUNDING_FIELDS - set(data))
    errors.extend(f"Missing v2 grounding field {field} in {path}" for field in missing)
    if missing:
        return errors
    if not data.get("checked_claims"):
        errors.append(f"grounding review checked_claims is empty in {path}")
    if data.get("requires_revision"):
        errors.append(f"grounding review requires_revision is true in {path}")
    for field in ["unsupported_claims", "missing_coverage", "template_or_style_issues"]:
        if data.get(field):
            errors.append(f"grounding review reports {field} in {path}")
    return errors


def report_template_errors(text: str, slide_count: int) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    phrase_hits = {phrase: text.count(phrase) for phrase in TEMPLATE_PHRASES}
    total_hits = sum(phrase_hits.values())
    threshold = max(2, slide_count // 5)
    if total_hits > threshold:
        errors.append(f"template repetition detected: {total_hits} stock phrase hits")
    repeated = {sentence: count for sentence, count in sentence_counts(text).items() if count >= 3}
    if repeated:
        sentence, count = next(iter(repeated.items()))
        errors.append(f"repeated sentence detected {count} times: {sentence[:90]}")
    return errors, {"template_phrase_hits": phrase_hits, "total_template_hits": total_hits, "repeated_sentence_count": len(repeated)}


def report_uses_cognition(text: str, cognition_paths: list[Path]) -> bool:
    normalized_report = normalize_text(text)
    for path in cognition_paths:
        if not path.exists():
            continue
        try:
            data = read_json(path)
        except Exception:
            continue
        for claim in data.get("main_claims", []):
            claim_text = normalize_text(str(claim))
            if len(claim_text) >= 24 and claim_text[:80] in normalized_report:
                return True
        for entity in data.get("numbers_and_entities", []):
            entity_text = normalize_text(str(entity))
            if len(entity_text) >= 5 and entity_text in normalized_report:
                return True
    return False


def report_uses_qa_pairs(text: str, qa_paths: list[Path]) -> bool:
    normalized_report = normalize_text(text)
    found_pairs = False
    for path in qa_paths:
        if not path.exists():
            continue
        try:
            data = read_json(path)
        except Exception:
            continue
        for pair in data.get("qa_pairs", []):
            if not isinstance(pair, dict):
                continue
            found_pairs = True
            question = normalize_text(str(pair.get("question", "")))
            answer = normalize_text(str(pair.get("answer", "")))
            if question[:40] in normalized_report or answer[:40] in normalized_report:
                return True
    return not found_pairs


def normalized_copy_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def report_task_evidence_path(task: dict[str, Any]) -> Path | None:
    if task.get("evidence_path"):
        return Path(str(task["evidence_path"]))
    for path in task.get("input_paths", []):
        candidate = Path(str(path))
        if candidate.name == "evidence.json":
            return candidate
    return None


def talk_dir_for_report_task(task: dict[str, Any]) -> Path | None:
    if task.get("talk_dir"):
        return Path(str(task["talk_dir"]))
    evidence_path = report_task_evidence_path(task)
    if evidence_path is not None:
        return evidence_path.parent
    for path in task.get("input_paths", []):
        candidate = Path(str(path))
        if candidate.name in {"metadata.json", "timeline.txt", "evidence.json"}:
            return candidate.parent
    return None


def canonical_qa_path(report_task: dict[str, Any], qa_tasks: list[dict[str, Any]]) -> Path | None:
    talk_dir = talk_dir_for_report_task(report_task)
    if talk_dir is not None:
        return talk_dir / "qa" / "qa_pairs.json"
    for task in qa_tasks:
        for output in task.get("output_paths", []):
            candidate = Path(str(output))
            if candidate.name == "qa_pairs.json":
                return candidate
    return None


def existing_or_manifest_qa_paths(report_task: dict[str, Any], qa_tasks: list[dict[str, Any]]) -> list[Path]:
    paths: list[Path] = []
    canonical = canonical_qa_path(report_task, qa_tasks)
    if canonical is not None and canonical.exists():
        paths.append(canonical)
    if not paths:
        for task in qa_tasks:
            for output in task.get("output_paths", []):
                path = Path(str(output))
                if path not in paths:
                    paths.append(path)
    return paths


def evidence_copy_and_coverage_errors(text: str, evidence_path: Path | None) -> tuple[list[str], dict[str, Any]]:
    if evidence_path is None or not evidence_path.exists():
        return [], {}
    try:
        evidence = read_json(evidence_path)
    except Exception:
        return [], {}
    if not isinstance(evidence, list):
        return [], {}
    errors: list[str] = []
    metrics: dict[str, Any] = {"expected_slide_count": len(evidence)}
    heading_numbers = {
        int(match.group(1))
        for match in re.finditer(r"^#{2,6}\s*第\s*(\d+)\s*张", text, flags=re.MULTILINE)
        if match.group(1).isdigit()
    }
    metrics["covered_slide_count"] = len(heading_numbers)
    missing_slides = [idx for idx in range(1, len(evidence) + 1) if idx not in heading_numbers]
    if missing_slides:
        errors.append(f"report is missing slide coverage for slide(s): {missing_slides[:5]}")
    normalized_report = normalized_copy_text(text)
    copy_hits: list[dict[str, Any]] = []
    for idx, row in enumerate(evidence, start=1):
        if not isinstance(row, dict):
            continue
        for field in ["ocr_text", "asr_text"]:
            source = normalized_copy_text(str(row.get(field, "")))
            if len(source) < 120:
                continue
            for start in range(0, len(source), 120):
                chunk = source[start : start + 120]
                if len(chunk) >= 90 and chunk in normalized_report:
                    copy_hits.append({"slide_index": idx, "field": field})
                    break
    metrics["evidence_copy_hit_count"] = len(copy_hits)
    if len(copy_hits) >= max(1, len(evidence) // 4):
        errors.append(f"report copies long OCR/ASR evidence chunks instead of synthesizing them: {copy_hits[:5]}")
    return errors, metrics


def repair_plan_command(out_dir: Path, command: str) -> str:
    return f"conference-report {command} --out {out_dir} --phase final" if command == "validate" else f"conference-report {command} --out {out_dir}"


def write_quality_repair_tasks(out_dir: Path, report_results: list[dict[str, Any]], grouped_tasks: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
    quality_path = (out_dir / REPORT_QUALITY_FILE).resolve()
    cognition_revision_tasks: list[dict[str, Any]] = []
    qa_revision_tasks: list[dict[str, Any]] = []
    report_revision_tasks: list[dict[str, Any]] = []
    grounding_revision_tasks: list[dict[str, Any]] = []
    grounding_by_slug = grouped_tasks.get("grounding_review", {})
    report_by_slug = grouped_tasks.get("report_write", {})
    cognition_by_slug = grouped_tasks.get("slide_cognition", {})
    qa_by_slug = grouped_tasks.get("qa_detection", {})
    for result in report_results:
        if result.get("ok"):
            continue
        slug = str(result.get("slug"))
        report_tasks = report_by_slug.get(slug) or []
        if not report_tasks:
            continue
        report_task = report_tasks[0]
        title = report_task.get("title", slug)
        issue_types = set(result.get("issue_types") or [])
        cognition_tasks = cognition_by_slug.get(slug, [])
        qa_tasks = qa_by_slug.get(slug, [])
        cognition_outputs = [str(output) for task in cognition_tasks for output in task.get("output_paths", [])]
        canonical_qa = canonical_qa_path(report_task, qa_tasks)
        qa_outputs = [str(canonical_qa.resolve())] if canonical_qa is not None else [str(output) for task in qa_tasks for output in task.get("output_paths", [])]
        report_outputs = list(report_task.get("output_paths", []))
        grounding_tasks = grounding_by_slug.get(slug, [])
        grounding_outputs = [str(output) for task in grounding_tasks for output in task.get("output_paths", [])]
        if "cognition_revision_required" in issue_types and cognition_outputs:
            cognition_inputs: list[str] = [str(quality_path)]
            for task in cognition_tasks:
                for input_path in task.get("input_paths", []):
                    if input_path not in cognition_inputs:
                        cognition_inputs.append(str(input_path))
            cognition_revision_tasks.append(
                {
                    "task_id": f"slide-cognition-revision:{slug}",
                    "stage": "slide_cognition_revision",
                    "slug": slug,
                    "title": title,
                    "input_paths": cognition_inputs,
                    "dependency_output_paths": [],
                    "output_paths": cognition_outputs,
                    "allowed_write_paths": cognition_outputs,
                    "required_schema": V2_SLIDE_COGNITION_SCHEMA,
                    "validation_rules": [
                        {"type": "json_fields", "required": sorted(V2_SLIDE_COGNITION_FIELDS)},
                        {"type": "semantic_depth"},
                        {"type": "allowed_writes"},
                    ],
                    "quality_errors": result.get("cognition_errors", [])[:8],
                    "done_condition": "Rewrite all listed slide_cognition JSON files with v2 semantic fields before QA/report revision.",
                }
            )
        if "qa_revision_required" in issue_types and qa_outputs:
            qa_inputs: list[str] = [str(quality_path)]
            for task in qa_tasks:
                for input_path in task.get("input_paths", []):
                    if input_path not in qa_inputs:
                        qa_inputs.append(str(input_path))
            qa_revision_tasks.append(
                {
                    "task_id": f"qa-revision:{slug}",
                    "stage": "qa_revision",
                    "slug": slug,
                    "title": title,
                    "input_paths": qa_inputs,
                    "dependency_output_paths": cognition_outputs,
                    "output_paths": qa_outputs,
                    "allowed_write_paths": qa_outputs,
                    "required_schema": V2_QA_SCHEMA,
                    "validation_rules": [
                        {"type": "json_fields", "required": sorted(V2_QA_FIELDS)},
                        {"type": "qa_pair_schema", "required": ["question", "answer", "time_range", "evidence_quotes", "confidence"]},
                        {"type": "allowed_writes"},
                    ],
                    "quality_errors": result.get("qa_errors", [])[:8],
                    "done_condition": "Write canonical qa_pairs.json; do not list transcript fragments as QA pairs.",
                }
            )
        if "report_revision_required" in issue_types and report_outputs:
            report_revision_tasks.append(
                {
                    "task_id": f"report-revision:{slug}",
                    "stage": "report_revision",
                    "slug": slug,
                    "title": title,
                    "input_paths": list(report_task.get("input_paths", [])) + [str(quality_path)],
                    "dependency_output_paths": cognition_outputs + qa_outputs,
                    "output_paths": report_outputs,
                    "allowed_write_paths": report_outputs,
                    "required_sections": report_task.get("required_sections", REPORT_REQUIRED_SECTIONS),
                    "validation_rules": [
                        {"type": "exists", "paths": "output_paths"},
                        {"type": "markdown_required_sections", "sections": report_task.get("required_sections", REPORT_REQUIRED_SECTIONS)},
                        {"type": "report_quality"},
                        {"type": "allowed_writes"},
                    ],
                    "quality_errors": result.get("report_errors", [])[:8],
                    "done_condition": "Rewrite only this Markdown report after cognition and QA revisions are complete.",
                }
            )
        if "grounding_revision_required" in issue_types and grounding_outputs:
            grounding_inputs: list[str] = [str(quality_path)]
            for task in grounding_tasks:
                for input_path in task.get("input_paths", []):
                    if input_path not in grounding_inputs:
                        grounding_inputs.append(str(input_path))
            grounding_revision_tasks.append(
                {
                    "task_id": f"grounding-revision:{slug}",
                    "stage": "grounding_revision",
                    "slug": slug,
                    "title": title,
                    "input_paths": grounding_inputs,
                    "dependency_output_paths": report_outputs + cognition_outputs + qa_outputs,
                    "output_paths": grounding_outputs,
                    "allowed_write_paths": grounding_outputs,
                    "required_schema": V2_GROUNDING_SCHEMA,
                    "validation_rules": [
                        {"type": "json_fields", "required": sorted(V2_GROUNDING_FIELDS)},
                        {"type": "claim_level_review"},
                        {"type": "allowed_writes"},
                    ],
                    "quality_errors": result.get("grounding_errors", [])[:8],
                    "done_condition": "Rewrite grounding review with non-empty checked_claims after the report has been revised.",
                }
            )
    manifests = {
        "slide_cognition_revision": SLIDE_COGNITION_REVISION_TASKS_FILE,
        "qa_revision": QA_REVISION_TASKS_FILE,
        "report_revision": REVISION_TASKS_FILE,
        "grounding_revision": GROUNDING_REVISION_TASKS_FILE,
    }
    write_json(out_dir / SLIDE_COGNITION_REVISION_TASKS_FILE, cognition_revision_tasks)
    write_json(out_dir / QA_REVISION_TASKS_FILE, qa_revision_tasks)
    write_json(out_dir / REVISION_TASKS_FILE, report_revision_tasks)
    write_json(out_dir / GROUNDING_REVISION_TASKS_FILE, grounding_revision_tasks)
    failed_reports = [item for item in report_results if not item.get("ok")]
    plan = {
        "blocked_gate": "report_quality_repair",
        "stages": QUALITY_REPAIR_STAGES,
        "reason": "report-quality failed" if failed_reports else "",
        "failed_reports": [
            {
                "slug": item.get("slug"),
                "report_path": item.get("report_path"),
                "issue_types": item.get("issue_types", []),
                "first_errors": item.get("errors", [])[:5],
            }
            for item in failed_reports
        ],
        "task_manifests": manifests,
        "repair_task_counts": {
            "slide_cognition_revision": len(cognition_revision_tasks),
            "qa_revision": len(qa_revision_tasks),
            "report_revision": len(report_revision_tasks),
            "grounding_revision": len(grounding_revision_tasks),
        },
        "next_allowed_command": repair_plan_command(out_dir, "validate"),
        "resume_command": repair_plan_command(out_dir, "resume"),
    }
    write_json(out_dir / QUALITY_REPAIR_PLAN_FILE, plan)


def write_revision_tasks(out_dir: Path, report_results: list[dict[str, Any]], grouped_tasks: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
    write_quality_repair_tasks(out_dir, report_results, grouped_tasks)


def validate_report_quality(out_dir: Path, errors: list[str]) -> dict[str, Any]:
    initial_error_count = len(errors)
    reports_manifest_path = out_dir / "reports_manifest.json"
    reports_manifest = read_json(reports_manifest_path) if reports_manifest_path.exists() else {}
    if reports_manifest.get("writer_mode") != "agent":
        result = {"ok": True, "phase": "report-quality", "reports": [], "manifest_errors": []}
        write_json(out_dir / REPORT_QUALITY_FILE, result)
        return result
    grouped = tasks_by_stage_and_slug(out_dir, errors)
    report_results: list[dict[str, Any]] = []
    for report_task in [task for tasks in grouped.get("report_write", {}).values() for task in tasks]:
        slug = str(report_task.get("slug", ""))
        report_path = Path(str(report_task.get("report_path") or (report_task.get("output_paths") or [""])[0]))
        cognition_errors: list[str] = []
        qa_errors: list[str] = []
        grounding_errors: list[str] = []
        report_content_errors: list[str] = []
        metrics: dict[str, Any] = {}
        cognition_paths = [Path(str(output)) for task in grouped.get("slide_cognition", {}).get(slug, []) for output in task.get("output_paths", [])]
        qa_tasks = grouped.get("qa_detection", {}).get(slug, [])
        qa_paths = existing_or_manifest_qa_paths(report_task, qa_tasks)
        grounding_paths = [Path(str(output)) for task in grouped.get("grounding_review", {}).get(slug, []) for output in task.get("output_paths", [])]
        for path in cognition_paths:
            cognition_errors.extend(validate_cognition_quality(path))
        for path in qa_paths:
            qa_errors.extend(validate_qa_quality(path))
        for path in grounding_paths:
            grounding_errors.extend(validate_grounding_quality(path))
        if not report_path.exists():
            report_content_errors.append(f"Missing report for quality validation: {report_path}")
        else:
            text = report_path.read_text(encoding="utf-8", errors="ignore")
            for section in missing_markdown_sections(report_path, REPORT_REQUIRED_SECTIONS):
                report_content_errors.append(f"Missing required section {section} in {report_path}")
            report_content_errors.extend(markdown_image_errors(report_path))
            evidence_errors, evidence_metrics = evidence_copy_and_coverage_errors(text, report_task_evidence_path(report_task))
            report_content_errors.extend(evidence_errors)
            metrics.update(evidence_metrics)
            template_errors, template_metrics = report_template_errors(text, len(cognition_paths))
            report_content_errors.extend(template_errors)
            metrics.update(template_metrics)
            if cognition_paths and not report_uses_cognition(text, cognition_paths):
                report_content_errors.append(f"report does not appear to use slide_cognition claims for {slug}")
            if qa_paths and not report_uses_qa_pairs(text, qa_paths):
                report_content_errors.append(f"report QA section does not appear to use qa_pairs for {slug}")
        issue_types: list[str] = []
        if cognition_errors:
            issue_types.append("cognition_revision_required")
        if qa_errors:
            issue_types.append("qa_revision_required")
        if report_content_errors:
            issue_types.append("report_revision_required")
        if grounding_errors:
            issue_types.append("grounding_revision_required")
        report_errors = cognition_errors + qa_errors + report_content_errors + grounding_errors
        report_results.append(
            {
                "slug": slug,
                "report_path": str(report_path),
                "ok": not report_errors,
                "errors": report_errors,
                "issue_types": issue_types,
                "cognition_errors": cognition_errors,
                "qa_errors": qa_errors,
                "report_errors": report_content_errors,
                "grounding_errors": grounding_errors,
                "metrics": metrics,
            }
        )
        errors.extend(report_errors)
    local_errors = errors[initial_error_count:]
    ok = not local_errors and not any(not item["ok"] for item in report_results)
    reports_manifest["final_reports"] = ok and not reports_manifest.get("pending_reports")
    failed_reports = [item["report_path"] for item in report_results if not item["ok"]]
    reports_manifest["quality_failed_reports"] = failed_reports
    if failed_reports:
        reports_manifest["pending_reports"] = failed_reports
    elif reports_manifest.get("planned_reports"):
        reports_manifest["pending_reports"] = []
        reports_manifest["completed_reports"] = list(reports_manifest.get("planned_reports", []))
        reports_manifest["reports"] = list(reports_manifest.get("planned_reports", []))
    write_json(out_dir / "reports_manifest.json", reports_manifest)
    result = {"ok": ok, "phase": "report-quality", "reports": report_results, "manifest_errors": local_errors}
    write_json(out_dir / REPORT_QUALITY_FILE, result)
    write_quality_repair_tasks(out_dir, report_results, grouped)
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

    if phase == "dedupe-review":
        validate_dedupe_review_tasks(out_dir, errors)
    else:
        validate_evidence(out_dir, errors, warnings)
    if phase in {"agent-tasks", "final"}:
        validate_agent_tasks(out_dir, phase=phase, errors=errors)
    if phase in {"report-quality", "final"}:
        validate_report_quality(out_dir, errors)
    validate_existing_report_links(out_dir, warnings, strict=phase == "final", errors=errors)

    result = {"ok": not errors, "phase": phase, "errors": errors, "warnings": warnings}
    write_json(out_dir / "validation.json", result)
    return result
