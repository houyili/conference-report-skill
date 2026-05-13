from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import read_json, write_json


AGENT_EXECUTION_PLAN_FILE = "agent_execution_plan.json"

REPAIR_STAGE_ORDER = [
    "slide_cognition_revision",
    "qa_revision",
    "report_revision",
    "grounding_revision",
]


def tasks_by_stage(tasks: dict[str, list[dict[str, Any]]] | list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    if isinstance(tasks, dict):
        return {str(stage): [task for task in stage_tasks if isinstance(task, dict)] for stage, stage_tasks in tasks.items()}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        grouped.setdefault(str(task.get("stage", "")), []).append(task)
    return grouped


def _unique_paths(tasks: list[dict[str, Any]], key: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for task in tasks:
        for value in task.get(key, []):
            if not isinstance(value, str) or value in seen:
                continue
            paths.append(value)
            seen.add(value)
    return paths


def _task_ids(tasks: list[dict[str, Any]]) -> list[str]:
    return [str(task.get("task_id")) for task in tasks if task.get("task_id")]


def _tasks_for_slug(grouped: dict[str, list[dict[str, Any]]], stage: str, slug: str) -> list[dict[str, Any]]:
    return [task for task in grouped.get(stage, []) if str(task.get("slug", "")) == slug]


def _slug_set(grouped: dict[str, list[dict[str, Any]]], stages: list[str]) -> list[str]:
    slugs = {
        str(task.get("slug"))
        for stage in stages
        for task in grouped.get(stage, [])
        if task.get("slug")
    }
    return sorted(slugs)


def _dependency_status_from_dispatch(dispatch_plan: dict[str, Any] | None) -> tuple[str, int, int, int, int]:
    if not isinstance(dispatch_plan, dict):
        return "unvalidated", 0, 0, 0, 0
    state = str(dispatch_plan.get("dependency_validation_state") or "unvalidated")
    workers = dispatch_plan.get("workers") if isinstance(dispatch_plan.get("workers"), list) else []
    ready = 0
    missing = 0
    invalid = 0
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        status = worker.get("dependency_status") if isinstance(worker.get("dependency_status"), dict) else {}
        if worker.get("dependencies_ready") or status.get("ready"):
            ready += 1
        missing += int(status.get("missing") or 0)
        invalid += int(status.get("invalid") or 0)
    return state, ready, max(0, len(workers) - ready), missing, invalid


def _dependency_status_from_file(status: dict[str, Any] | None) -> tuple[str | None, int | None, int | None, int | None, int | None]:
    if not isinstance(status, dict):
        return None, None, None, None, None
    state = str(status.get("dependency_validation_state") or status.get("phase") or "validated")
    report_tasks = status.get("report_tasks") if isinstance(status.get("report_tasks"), dict) else {}
    missing = 0
    invalid = 0
    for item in report_tasks.values():
        if not isinstance(item, dict):
            continue
        missing += int(item.get("missing") or 0)
        invalid += int(item.get("invalid") or 0)
    return (
        state,
        int(status.get("ready_report_tasks") or 0),
        int(status.get("blocked_report_tasks") or 0),
        missing,
        invalid,
    )


def _dependency_groups(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for slug in _slug_set(grouped, ["slide_cognition", "qa_detection"]):
        tasks = _tasks_for_slug(grouped, "slide_cognition", slug) + _tasks_for_slug(grouped, "qa_detection", slug)
        if not tasks:
            continue
        groups.append(
            {
                "group_id": f"dependencies:{slug}",
                "slug": slug,
                "stages": ["slide_cognition", "qa_detection"],
                "task_ids": _task_ids(tasks),
                "task_count": len(tasks),
                "parent_sequential_ok": True,
                "parallel_worker_optional": True,
                "recommended_parallel_scope": "one optional worker per talk when the user authorizes parallel agents",
                "input_paths": _unique_paths(tasks, "input_paths"),
                "output_paths": _unique_paths(tasks, "output_paths"),
                "allowed_write_paths": _unique_paths(tasks, "allowed_write_paths"),
                "worker_prompt_contract": {
                    "agent_neutral": True,
                    "scope": "Complete slide cognition and QA outputs for this talk only.",
                    "path_rule": "Use absolute paths exactly as listed; do not infer another run directory.",
                    "write_rule": "Write only allowed_write_paths and do not edit manifests or pipeline_state.json.",
                },
            }
        )
    return groups


def _report_groups(
    grouped: dict[str, list[dict[str, Any]]],
    dispatch_plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    workers = dispatch_plan.get("workers") if isinstance(dispatch_plan, dict) and isinstance(dispatch_plan.get("workers"), list) else []
    groups: list[dict[str, Any]] = []
    if workers:
        for worker in workers:
            if not isinstance(worker, dict):
                continue
            status = worker.get("dependency_status") if isinstance(worker.get("dependency_status"), dict) else {}
            groups.append(
                {
                    "group_id": str(worker.get("worker_id") or f"report-writer:{worker.get('slug', len(groups) + 1)}"),
                    "slug": worker.get("slug"),
                    "stage": "report_write",
                    "task_id": worker.get("task_id"),
                    "requires_subagent": True,
                    "isolation_scope": "single_report",
                    "dependencies_ready": bool(worker.get("dependencies_ready") or status.get("ready")),
                    "dependency_status": status,
                    "input_paths": worker.get("input_paths") or [],
                    "dependency_output_paths": worker.get("dependency_output_paths") or [],
                    "output_paths": worker.get("output_paths") or [],
                    "allowed_write_paths": worker.get("allowed_write_paths") or [],
                    "execution_provenance_path": worker.get("execution_provenance_path"),
                    "worker_prompt_contract": {
                        "agent_neutral": True,
                        "scope": "One clean subagent context writes exactly this final report.",
                        "first_step": "Write talk_synthesis.md before drafting the final Markdown report.",
                        "provenance_rule": "Write report_writer_provenance.json with worker_type=subagent and isolation_scope=single_report.",
                    },
                }
            )
        return groups
    for task in grouped.get("report_write", []):
        groups.append(
            {
                "group_id": f"report-writer:{task.get('slug', len(groups) + 1)}",
                "slug": task.get("slug"),
                "stage": "report_write",
                "task_id": task.get("task_id"),
                "requires_subagent": True,
                "isolation_scope": "single_report",
                "dependencies_ready": False,
                "dependency_status": {},
                "input_paths": task.get("input_paths", []),
                "dependency_output_paths": task.get("dependency_output_paths", []),
                "output_paths": task.get("output_paths", []),
                "allowed_write_paths": task.get("allowed_write_paths", []),
                "execution_provenance_path": task.get("execution_provenance_path"),
            }
        )
    return groups


def _grounding_groups(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for slug in _slug_set(grouped, ["grounding_review"]):
        tasks = _tasks_for_slug(grouped, "grounding_review", slug)
        groups.append(
            {
                "group_id": f"grounding:{slug}",
                "slug": slug,
                "stage": "grounding_review",
                "task_ids": _task_ids(tasks),
                "task_count": len(tasks),
                "runs_after": ["report_write"],
                "parent_sequential_ok": True,
                "parallel_worker_optional": True,
                "input_paths": _unique_paths(tasks, "input_paths"),
                "dependency_output_paths": _unique_paths(tasks, "dependency_output_paths"),
                "output_paths": _unique_paths(tasks, "output_paths"),
                "allowed_write_paths": _unique_paths(tasks, "allowed_write_paths"),
            }
        )
    return groups


def _read_repair_tasks(out_dir: Path, repair_plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    manifests = repair_plan.get("task_manifests") if isinstance(repair_plan.get("task_manifests"), dict) else {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for stage, value in manifests.items():
        path = Path(str(value))
        if not path.is_absolute():
            path = out_dir / path
        if not path.exists():
            grouped[str(stage)] = []
            continue
        try:
            tasks = read_json(path)
        except Exception:
            tasks = []
        grouped[str(stage)] = [task for task in tasks if isinstance(task, dict)] if isinstance(tasks, list) else []
    return grouped


def _repair_groups(out_dir: Path, repair_plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(repair_plan, dict) or repair_plan.get("resolved"):
        return []
    counts = repair_plan.get("active_repair_task_counts") or repair_plan.get("repair_task_counts") or {}
    active_stages = repair_plan.get("active_stages")
    if not isinstance(active_stages, list):
        active_stages = [stage for stage in REPAIR_STAGE_ORDER if int(counts.get(stage) or 0) > 0]
    repair_tasks = _read_repair_tasks(out_dir, repair_plan)
    groups: list[dict[str, Any]] = []
    for stage in [stage for stage in REPAIR_STAGE_ORDER if stage in active_stages]:
        for slug in _slug_set(repair_tasks, [stage]):
            tasks = _tasks_for_slug(repair_tasks, stage, slug)
            requires_subagent = any(bool(task.get("requires_subagent")) for task in tasks)
            groups.append(
                {
                    "group_id": f"repair:{stage}:{slug}",
                    "slug": slug,
                    "stage": stage,
                    "task_ids": _task_ids(tasks),
                    "task_count": len(tasks),
                    "requires_subagent": requires_subagent,
                    "parent_sequential_ok": not requires_subagent,
                    "runs_after": ["report_revision"] if stage == "grounding_revision" else [],
                    "input_paths": _unique_paths(tasks, "input_paths"),
                    "dependency_output_paths": _unique_paths(tasks, "dependency_output_paths"),
                    "output_paths": _unique_paths(tasks, "output_paths"),
                    "allowed_write_paths": _unique_paths(tasks, "allowed_write_paths"),
                }
            )
    return groups


def build_agent_execution_plan(
    out_dir: Path,
    tasks: dict[str, list[dict[str, Any]]] | list[dict[str, Any]],
    *,
    dispatch_plan: dict[str, Any] | None = None,
    dependency_status: dict[str, Any] | None = None,
    repair_plan: dict[str, Any] | None = None,
    dependency_validation_state: str | None = None,
) -> dict[str, Any]:
    grouped = tasks_by_stage(tasks)
    if dispatch_plan is None and (out_dir / "agent_report_dispatch_plan.json").exists():
        try:
            dispatch_plan = read_json(out_dir / "agent_report_dispatch_plan.json")
        except Exception:
            dispatch_plan = {}
    if dependency_status is None and (out_dir / "agent_dependency_status.json").exists():
        try:
            dependency_status = read_json(out_dir / "agent_dependency_status.json")
        except Exception:
            dependency_status = {}
    if repair_plan is None and (out_dir / "agent_quality_repair_plan.json").exists():
        try:
            repair_plan = read_json(out_dir / "agent_quality_repair_plan.json")
        except Exception:
            repair_plan = {}

    file_state, file_ready, file_blocked, file_missing, file_invalid = _dependency_status_from_file(dependency_status)
    dispatch_state, dispatch_ready, dispatch_blocked, dispatch_missing, dispatch_invalid = _dependency_status_from_dispatch(dispatch_plan)
    validation_state = dependency_validation_state or file_state or dispatch_state
    ready = file_ready if file_ready is not None else dispatch_ready
    blocked = file_blocked if file_blocked is not None else dispatch_blocked
    missing = file_missing if file_missing is not None else dispatch_missing
    invalid = file_invalid if file_invalid is not None else dispatch_invalid

    dependency_groups = _dependency_groups(grouped)
    report_groups = _report_groups(grouped, dispatch_plan)
    grounding_groups = _grounding_groups(grouped)
    repair_groups = _repair_groups(out_dir, repair_plan)
    active_repair_stages = sorted({str(group["stage"]) for group in repair_groups}, key=lambda item: REPAIR_STAGE_ORDER.index(item) if item in REPAIR_STAGE_ORDER else 99)
    required_report_subagents = len(report_groups)
    return {
        "schema_version": 1,
        "stage": "report_agent",
        "run_dir": str(out_dir.resolve()),
        "dependency_validation_state": validation_state,
        "execution_order": [
            "dependency_worker_groups",
            "validate --phase agent-tasks",
            "ready report_worker_groups",
            "grounding_worker_groups",
            "validate --phase final",
            "repair_worker_groups if report_quality fails",
            "resume",
        ],
        "required_subagent_stages": ["report_write"],
        "parent_sequential_allowed_stages": ["slide_cognition", "qa_detection", "grounding_review"],
        "required_report_subagents": required_report_subagents,
        "subagent_budget": {
            "minimum_required": required_report_subagents,
            "optional_dependency_worker_groups": len(dependency_groups),
            "optional_repair_worker_groups": len(repair_groups),
            "maximum_if_all_optional_parallel": required_report_subagents + len(dependency_groups) + len(repair_groups),
        },
        "current_status": {
            "ready_report_tasks": ready,
            "blocked_report_tasks": blocked,
            "missing_dependency_outputs": missing,
            "invalid_dependency_outputs": invalid,
            "active_repair_stages": active_repair_stages,
        },
        "dependency_worker_groups": dependency_groups,
        "report_worker_groups": report_groups,
        "grounding_worker_groups": grounding_groups,
        "repair_worker_groups": repair_groups,
    }


def write_agent_execution_plan(
    out_dir: Path,
    tasks: dict[str, list[dict[str, Any]]] | list[dict[str, Any]],
    *,
    dispatch_plan: dict[str, Any] | None = None,
    dependency_status: dict[str, Any] | None = None,
    repair_plan: dict[str, Any] | None = None,
    dependency_validation_state: str | None = None,
) -> dict[str, Any]:
    plan = build_agent_execution_plan(
        out_dir,
        tasks,
        dispatch_plan=dispatch_plan,
        dependency_status=dependency_status,
        repair_plan=repair_plan,
        dependency_validation_state=dependency_validation_state,
    )
    write_json(out_dir / AGENT_EXECUTION_PLAN_FILE, plan)
    return plan
