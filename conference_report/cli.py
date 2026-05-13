from __future__ import annotations

import argparse
from pathlib import Path

from .agent_flow import AGENT_EXECUTION_PLAN_FILE
from .auth import credential_status, delete_secret, set_secret_interactive
from .asr import run_asr
from .config import CONFIG_PROFILES, load_config, write_default_config
from .dedupe import apply_dedupe_agent_reviews, dedupe_slides
from .ingest import ingest
from .pipeline_state import (
    blocked_command_message,
    format_state_for_human,
    is_waiting,
    read_pipeline_state,
    write_completed_state,
    write_waiting_state,
)
from .report import (
    REPORT_DISPATCH_PLAN_FILE,
    REPORT_SUBAGENT_AUTHORIZATION_MESSAGE,
    REPORT_SUBAGENT_FALLBACK_OPTIONS,
    generate_reports,
)
from .segment import segment
from .slides import extract_slides
from .utils import read_json, write_json
from .validate import AGENT_DEPENDENCY_STATUS_FILE, QUALITY_REPAIR_MANIFESTS, QUALITY_REPAIR_PLAN_FILE, REVISION_TASKS_FILE, validate_run


WRITER_CHOICES = ["auto", "agent", "openai", "evidence"]
PIPELINE_COMMANDS = {"build", "ingest", "asr", "slides", "dedupe", "segment", "report"}


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--cookies-from-browser")


def add_profile_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        choices=CONFIG_PROFILES,
        default="full",
        help=(
            "Config template to use before file overrides. "
            "'fast' skips optional audio preservation when subtitles are available; 'full' keeps audit artifacts."
        ),
    )


def add_writer_options(parser: argparse.ArgumentParser, *, build: bool = False) -> None:
    parser.add_argument("--writer", choices=WRITER_CHOICES, default="auto")
    if build:
        parser.add_argument("--dry-run-report", action="store_true", help="Compatibility alias for --writer evidence.")
    else:
        parser.add_argument("--dry-run", action="store_true", help="Compatibility alias for --writer evidence.")


def selected_writer(args: argparse.Namespace, *, build: bool = False) -> str:
    dry_run = args.dry_run_report if build else args.dry_run
    return "evidence" if dry_run else args.writer


def parse_agent_gates(value: str | None) -> list[str]:
    if not value:
        return []
    aliases = {"dedupe": "dedupe", "dedupe-review": "dedupe", "report": "report", "report-agent": "report"}
    gates: list[str] = []
    for raw in value.split(","):
        item = raw.strip().lower()
        if not item:
            continue
        if item not in aliases:
            raise SystemExit(f"Unsupported agent gate: {raw}")
        gate = aliases[item]
        if gate not in gates:
            gates.append(gate)
    return gates


def print_validation_feedback(result: dict[str, object], *, next_hint: str | None = None) -> None:
    print("Validation failed.")
    print(f"Phase: {result.get('phase')}")
    errors = result.get("errors") or []
    if errors:
        print("First failed checks:")
        for error in list(errors)[:3]:
            print(f"- {error}")
    if next_hint:
        print(next_hint)


def prepare_build_config(args: argparse.Namespace, out: Path) -> dict[str, object]:
    profile = getattr(args, "profile", "full")
    if args.config is None:
        args.config = out / "run-config.yaml"
        write_default_config(args.config, profile=profile)
        print(f"Wrote run config: {args.config}")
    cfg = load_config(args.config, profile=profile)
    print(f"Using output dir: {out}")
    print(f"Using config: {args.config}")
    print(f"Using config profile: {profile}")
    if not cfg.get("asr", {}).get("save_audio", True):
        print("ASR/audio: skips optional audio preservation when subtitles are available; fallback ASR can still download audio.")
    return cfg


def config_path_from_state(out: Path) -> Path | None:
    state = read_pipeline_state(out)
    if not state or not state.get("config_path"):
        return None
    return Path(str(state["config_path"]))


def report_task_manifests(out: Path) -> list[str]:
    def display_path(value: str) -> str:
        path = Path(value)
        try:
            return str(path.resolve().relative_to(out.resolve()))
        except ValueError:
            return str(path)

    reports_manifest_path = out / "reports_manifest.json"
    if not reports_manifest_path.exists():
        return [
            AGENT_EXECUTION_PLAN_FILE,
            REPORT_DISPATCH_PLAN_FILE,
            AGENT_DEPENDENCY_STATUS_FILE,
            "agent_slide_cognition_tasks.json",
            "agent_qa_tasks.json",
            "agent_report_tasks.json",
            "agent_grounding_tasks.json",
        ]
    reports_manifest = read_json(reports_manifest_path)
    task_manifests = reports_manifest.get("task_manifests") or {}
    if isinstance(task_manifests, dict):
        manifests = [display_path(str(path)) for path in task_manifests.values()]
        if REPORT_DISPATCH_PLAN_FILE not in manifests:
            manifests.insert(0, REPORT_DISPATCH_PLAN_FILE)
        if AGENT_EXECUTION_PLAN_FILE not in manifests:
            manifests.insert(0, AGENT_EXECUTION_PLAN_FILE)
        if (out / AGENT_DEPENDENCY_STATUS_FILE).exists() and AGENT_DEPENDENCY_STATUS_FILE not in manifests:
            manifests.insert(1, AGENT_DEPENDENCY_STATUS_FILE)
        return manifests
    return [
        AGENT_EXECUTION_PLAN_FILE,
        REPORT_DISPATCH_PLAN_FILE,
        AGENT_DEPENDENCY_STATUS_FILE,
        "agent_slide_cognition_tasks.json",
        "agent_qa_tasks.json",
        "agent_report_tasks.json",
        "agent_grounding_tasks.json",
    ]


def report_subagent_dispatch_metadata(out: Path) -> dict[str, object]:
    dispatch_path = out / REPORT_DISPATCH_PLAN_FILE
    if dispatch_path.exists():
        try:
            dispatch = read_json(dispatch_path)
        except Exception:
            dispatch = {}
    else:
        dispatch = {}
    report_tasks_path = out / "agent_report_tasks.json"
    try:
        report_tasks = read_json(report_tasks_path) if report_tasks_path.exists() else []
    except Exception:
        report_tasks = []
    if not isinstance(report_tasks, list):
        report_tasks = []
    workers = dispatch.get("workers") if isinstance(dispatch, dict) else []
    if not isinstance(workers, list) or not workers:
        workers = [
            {
                "task_id": task.get("task_id"),
                "slug": task.get("slug"),
                "report_path": task.get("report_path"),
                "execution_provenance_path": task.get("execution_provenance_path"),
            }
            for task in report_tasks
            if isinstance(task, dict)
        ]
    pending = []
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        task = worker.get("task") if isinstance(worker.get("task"), dict) else {}
        pending.append(
            {
                "task_id": worker.get("task_id") or task.get("task_id"),
                "slug": worker.get("slug") or task.get("slug"),
                "report_path": worker.get("report_path") or task.get("report_path"),
                "execution_provenance_path": worker.get("execution_provenance_path") or task.get("execution_provenance_path"),
                "dependencies_ready": bool(worker.get("dependencies_ready")),
                "dependency_status": worker.get("dependency_status") if isinstance(worker.get("dependency_status"), dict) else {},
            }
        )
    required_count = dispatch.get("required_report_subagents") if isinstance(dispatch, dict) else None
    if required_count is None:
        required_count = len(report_tasks)
    return {
        "requires_subagents": True,
        "required_report_subagents": required_count,
        "subagent_required_stage": "report_write",
        "authorization_message": str(dispatch.get("authorization_message") or REPORT_SUBAGENT_AUTHORIZATION_MESSAGE)
        if isinstance(dispatch, dict)
        else REPORT_SUBAGENT_AUTHORIZATION_MESSAGE,
        "fallback_options": dispatch.get("fallback_options", REPORT_SUBAGENT_FALLBACK_OPTIONS)
        if isinstance(dispatch, dict)
        else REPORT_SUBAGENT_FALLBACK_OPTIONS,
        "dispatch_plan": REPORT_DISPATCH_PLAN_FILE,
        "pending_report_subagents": pending,
    }


def report_dependency_summary(out: Path) -> dict[str, object]:
    dependency_path = out / AGENT_DEPENDENCY_STATUS_FILE
    if dependency_path.exists():
        try:
            dependency = read_json(dependency_path)
        except Exception:
            dependency = {}
        report_tasks = dependency.get("report_tasks") if isinstance(dependency.get("report_tasks"), dict) else {}
        return {
            "agent_dependency_status": AGENT_DEPENDENCY_STATUS_FILE,
            "dependency_validation_state": str(dependency.get("dependency_validation_state") or dependency.get("phase") or "validated"),
            "agent_tasks_validation_ok": dependency.get("agent_tasks_validation_ok"),
            "ready_report_tasks": int(dependency.get("ready_report_tasks") or 0),
            "blocked_report_tasks": int(dependency.get("blocked_report_tasks") or 0),
            "total_report_tasks": len(report_tasks),
            "missing_dependency_outputs": int(dependency.get("missing_dependency_outputs") or 0),
            "invalid_dependency_outputs": int(dependency.get("invalid_dependency_outputs") or 0),
        }
    dispatch_path = out / REPORT_DISPATCH_PLAN_FILE
    try:
        dispatch = read_json(dispatch_path) if dispatch_path.exists() else {}
    except Exception:
        dispatch = {}
    workers = dispatch.get("workers") if isinstance(dispatch.get("workers"), list) else []
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
    return {
        "agent_dependency_status": AGENT_DEPENDENCY_STATUS_FILE if dependency_path.exists() else "",
        "dependency_validation_state": str(dispatch.get("dependency_validation_state") or "unvalidated"),
        "agent_tasks_validation_ok": dispatch.get("agent_tasks_validation_ok"),
        "ready_report_tasks": ready,
        "blocked_report_tasks": max(0, len(workers) - ready),
        "total_report_tasks": len(workers),
        "missing_dependency_outputs": missing,
        "invalid_dependency_outputs": invalid,
    }


def quality_repair_summary(out: Path) -> dict[str, object]:
    plan_path = out / QUALITY_REPAIR_PLAN_FILE
    if not plan_path.exists():
        return {}
    try:
        plan = read_json(plan_path)
    except Exception:
        return {"agent_quality_repair_plan": QUALITY_REPAIR_PLAN_FILE}
    if not isinstance(plan, dict):
        return {"agent_quality_repair_plan": QUALITY_REPAIR_PLAN_FILE}
    active_stages = plan.get("active_stages")
    if not isinstance(active_stages, list):
        counts = plan.get("active_repair_task_counts") or plan.get("repair_task_counts") or {}
        active_stages = [stage for stage, count in counts.items() if int(count or 0) > 0]
    return {
        "agent_quality_repair_plan": QUALITY_REPAIR_PLAN_FILE,
        "active_repair_stages": active_stages if not plan.get("resolved") else [],
        "repair_plan_resolved": bool(plan.get("resolved")),
        "active_repair_task_counts": plan.get("active_repair_task_counts") or {},
    }


def enrich_agent_flow_state(out: Path, state: dict[str, object]) -> dict[str, object]:
    enriched = dict(state)
    if (out / AGENT_EXECUTION_PLAN_FILE).exists() or enriched.get("blocked_gate") == "report_agent":
        enriched["agent_execution_plan"] = AGENT_EXECUTION_PLAN_FILE
    if enriched.get("blocked_gate") == "report_agent":
        enriched.update(report_dependency_summary(out))
    if enriched.get("blocked_gate") == "report_quality_repair":
        enriched.update(quality_repair_summary(out))
    return enriched


def validation_command(out: Path, state: dict[str, object], phase: str) -> str:
    config_arg = f" --config {state['config_path']}" if state.get("config_path") else ""
    return f"conference-report validate --out {out}{config_arg} --phase {phase}"


def refresh_report_gate_after_agent_tasks(out: Path, *, result: dict[str, object]) -> None:
    state = read_pipeline_state(out)
    if not state or state.get("blocked_gate") != "report_agent":
        return
    enriched = enrich_agent_flow_state(out, state)
    ready = int(enriched.get("ready_report_tasks") or 0)
    total = int(enriched.get("total_report_tasks") or 0)
    invalid = int(enriched.get("invalid_dependency_outputs") or 0)
    missing = int(enriched.get("missing_dependency_outputs") or 0)
    if result.get("ok") and total and ready == total and invalid == 0 and missing == 0:
        enriched["next_allowed_command"] = validation_command(out, enriched, "final")
        enriched["dispatch_guidance"] = (
            "Dependency validation passed. Dispatch one clean report_write subagent per ready report task, "
            "complete grounding_review outputs, then run final validation and resume."
        )
    else:
        enriched["next_allowed_command"] = validation_command(out, enriched, "agent-tasks")
        enriched["dispatch_guidance"] = (
            "Complete or repair slide_cognition and qa_detection dependency outputs, then rerun validate --phase agent-tasks. "
            "Do not dispatch report_write for tasks whose dependencies_ready is false."
        )
    write_json(out / "pipeline_state.json", enriched)


def pause_for_report_agent(out: Path, args: argparse.Namespace, completed_stages: list[str], writer: str) -> None:
    write_waiting_state(
        out,
        source=getattr(args, "source", None),
        completed_stages=completed_stages,
        blocked_gate="report_agent",
        config_path=getattr(args, "config", None),
        writer=writer,
        manual_segments=getattr(args, "manual_segments", None),
        agent_gates=getattr(args, "agent_gates_list", []),
    )
    state = read_pipeline_state(out) or {}
    state["task_manifests"] = report_task_manifests(out)
    state.update(report_subagent_dispatch_metadata(out))
    state.update(report_dependency_summary(out))
    if (out / AGENT_EXECUTION_PLAN_FILE).exists():
        state["agent_execution_plan"] = AGENT_EXECUTION_PLAN_FILE
    state["human_message"] = "\n".join(
        [
            str(state.get("human_message") or ""),
            "先运行 validate --phase agent-tasks 刷新 dependency readiness；只有 dependencies_ready: true 的 report task 可以 dispatch。",
            "report_write 需要用户明确授权为每个 report task 启动独立 subagent。",
            "父 agent 可以顺序完成 slide_cognition、qa_detection 和 grounding_review，但不能在父上下文里代写最终报告。",
            "如果不授权 subagents，本 run 可以停在 evidence/gate；请改用 --writer evidence 或 --writer openai，不要伪装成 agent-written final report。",
        ]
    ).strip()
    state["next_allowed_command"] = validation_command(out, state, "agent-tasks")
    write_json(out / "pipeline_state.json", state)
    print(format_state_for_human(state))


def status_state(out: Path) -> dict[str, object] | None:
    state = read_pipeline_state(out)
    if not state:
        return None
    if state.get("blocked_gate") != "report_agent":
        return enrich_agent_flow_state(out, state)
    enriched = dict(state)
    enriched["task_manifests"] = report_task_manifests(out)
    for key, value in report_subagent_dispatch_metadata(out).items():
        if not enriched.get(key):
            enriched[key] = value
    return enrich_agent_flow_state(out, enriched)


def revision_task_manifests(out: Path) -> list[str]:
    manifests = ["report_quality_validation.json"]
    if (out / REVISION_TASKS_FILE).exists():
        manifests.append(REVISION_TASKS_FILE)
    return manifests


def quality_repair_task_manifests(out: Path) -> list[str]:
    plan_path = out / QUALITY_REPAIR_PLAN_FILE
    if plan_path.exists():
        try:
            plan = read_json(plan_path)
            manifests = plan.get("task_manifests") or {}
            if isinstance(manifests, dict):
                return [QUALITY_REPAIR_PLAN_FILE] + [str(value) for value in manifests.values()]
        except Exception:
            pass
    manifests = [QUALITY_REPAIR_PLAN_FILE]
    manifests.extend(QUALITY_REPAIR_MANIFESTS.values())
    return manifests


def has_revision_tasks(out: Path) -> bool:
    path = out / REVISION_TASKS_FILE
    if not path.exists():
        return False
    try:
        tasks = read_json(path)
    except Exception:
        return True
    return isinstance(tasks, list) and len(tasks) > 0


def has_quality_repair_plan(out: Path) -> bool:
    path = out / QUALITY_REPAIR_PLAN_FILE
    if not path.exists():
        return False
    try:
        plan = read_json(path)
    except Exception:
        return True
    if plan.get("resolved"):
        return False
    failed = plan.get("failed_reports")
    if isinstance(failed, list):
        return len(failed) > 0
    return False


def pause_for_report_revision(out: Path, args: argparse.Namespace, completed_stages: list[str], writer: str | None = None) -> dict[str, object]:
    state = write_waiting_state(
        out,
        source=getattr(args, "source", None),
        completed_stages=completed_stages,
        blocked_gate="report_revision",
        config_path=getattr(args, "config", None),
        writer=writer or getattr(args, "writer", None),
        manual_segments=getattr(args, "manual_segments", None),
        agent_gates=getattr(args, "agent_gates_list", []),
    )
    state["task_manifests"] = revision_task_manifests(out)
    quality_path = out / "report_quality_validation.json"
    quality = read_json(quality_path) if quality_path.exists() else {}
    failed_reports = [item for item in quality.get("reports", []) if isinstance(item, dict) and not item.get("ok")]
    if failed_reports:
        examples: list[str] = []
        for item in failed_reports[:3]:
            errors = item.get("errors") or []
            first_error = str(errors[0]) if errors else "quality check failed"
            examples.append(f"- {item.get('slug')}: {first_error}")
        state["human_message"] = "\n".join(
            [
                str(state.get("human_message") or ""),
                "质量检查失败的报告:",
                *examples,
            ]
        ).strip()
    config_arg = f" --config {state['config_path']}" if state.get("config_path") else ""
    state["next_allowed_command"] = f"conference-report validate --out {out}{config_arg} --phase final"
    state["resume_command"] = f"conference-report resume --out {out}{config_arg}"
    write_json(out / "pipeline_state.json", state)
    print(format_state_for_human(state))
    return state


def pause_for_report_quality_repair(out: Path, args: argparse.Namespace, completed_stages: list[str], writer: str | None = None) -> dict[str, object]:
    state = write_waiting_state(
        out,
        source=getattr(args, "source", None),
        completed_stages=completed_stages,
        blocked_gate="report_quality_repair",
        config_path=getattr(args, "config", None),
        writer=writer or getattr(args, "writer", None),
        manual_segments=getattr(args, "manual_segments", None),
        agent_gates=getattr(args, "agent_gates_list", []),
    )
    state["task_manifests"] = quality_repair_task_manifests(out)
    plan_path = out / QUALITY_REPAIR_PLAN_FILE
    plan = read_json(plan_path) if plan_path.exists() else {}
    state.update(quality_repair_summary(out))
    if (out / AGENT_EXECUTION_PLAN_FILE).exists():
        state["agent_execution_plan"] = AGENT_EXECUTION_PLAN_FILE
    failed_reports = plan.get("failed_reports") if isinstance(plan.get("failed_reports"), list) else []
    state["failed_report_count"] = len(failed_reports)
    if failed_reports:
        examples: list[str] = []
        for item in failed_reports[:3]:
            if not isinstance(item, dict):
                continue
            first_errors = item.get("first_errors") or []
            first_error = str(first_errors[0]) if first_errors else "quality check failed"
            examples.append(f"- {item.get('slug')}: {first_error}")
        state["human_message"] = "\n".join(
            [
                str(state.get("human_message") or ""),
                "质量修复计划已生成。失败报告:",
                *examples,
            ]
        ).strip()
    config_arg = f" --config {state['config_path']}" if state.get("config_path") else ""
    state["next_allowed_command"] = f"conference-report validate --out {out}{config_arg} --phase final"
    state["resume_command"] = f"conference-report resume --out {out}{config_arg}"
    write_json(out / "pipeline_state.json", state)
    print(format_state_for_human(state))
    return state


def resume_pipeline(out: Path, cfg: dict[str, object], args: argparse.Namespace) -> int:
    state = read_pipeline_state(out)
    if not state:
        print("No pipeline_state.json found. There is no paused agent gate to resume.")
        return 0
    if not is_waiting(state):
        print(format_state_for_human(state))
        return 0
    gate = state.get("blocked_gate")
    if gate == "dedupe_review":
        validation = validate_run(out, phase="dedupe-review")
        if not validation["ok"]:
            print_validation_feedback(
                validation,
                next_hint="请先完成 dedupe/agent_review_tasks.json 中每个任务的 output_paths，然后再次运行 resume。",
            )
            return 1
        apply_dedupe_agent_reviews(out, cfg)
        completed_stages = list(state.get("completed_stages") or [])
        if "dedupe_review" not in completed_stages:
            completed_stages.append("dedupe_review")
        manual_segments = Path(state["manual_segments"]) if state.get("manual_segments") else None
        segment(out, cfg, manual_segments=manual_segments)
        completed_stages.append("segment")
        writer = str(state.get("writer") or cfg.get("report", {}).get("writer", "auto"))
        generate_reports(out, cfg, writer=writer)
        completed_stages.append("report")
        reports_manifest = read_json(out / "reports_manifest.json") if (out / "reports_manifest.json").exists() else {}
        if reports_manifest.get("writer_mode") == "agent":
            validation = validate_run(out, phase="agent-tasks")
            completed_stages.append("validate")
            if not validation["ok"]:
                print_validation_feedback(validation, next_hint="Agent task contract validation failed; fix manifests before continuing.")
                return 1
            state_args = argparse.Namespace(
                source=state.get("source"),
                config=args.config or (Path(state["config_path"]) if state.get("config_path") else None),
                manual_segments=manual_segments,
                agent_gates_list=state.get("agent_gates") or [],
            )
            pause_for_report_agent(out, state_args, completed_stages, writer)
            return 0
        phase = "final" if reports_manifest.get("writer_mode") == "openai" else "evidence"
        validation = validate_run(out, phase=phase)
        completed_stages.append("validate")
        if validation["ok"]:
            write_completed_state(out, source=state.get("source"), completed_stages=completed_stages)
            print("Pipeline completed.")
            return 0
        print_validation_feedback(validation)
        return 1
    if gate == "report_agent":
        validation = validate_run(out, phase="final")
        if validation["ok"]:
            completed_stages = list(state.get("completed_stages") or [])
            if "final" not in completed_stages:
                completed_stages.append("final")
            write_completed_state(out, source=state.get("source"), completed_stages=completed_stages)
            print("Final reports validated. Pipeline completed.")
            return 0
        if has_quality_repair_plan(out):
            completed_stages = list(state.get("completed_stages") or [])
            if "report_quality" not in completed_stages:
                completed_stages.append("report_quality")
            revision_args = argparse.Namespace(
                source=state.get("source"),
                config=args.config or (Path(state["config_path"]) if state.get("config_path") else None),
                manual_segments=Path(state["manual_segments"]) if state.get("manual_segments") else None,
                agent_gates_list=state.get("agent_gates") or [],
                writer=state.get("writer"),
            )
            pause_for_report_quality_repair(out, revision_args, completed_stages, str(state.get("writer") or "agent"))
            return 1
        print_validation_feedback(
            validation,
            next_hint="请只修复失败 task 的 allowed_write_paths，然后再次运行 validate --phase final 或 resume。",
        )
        return 1
    if gate in {"report_revision", "report_quality_repair"}:
        validation = validate_run(out, phase="final")
        if validation["ok"]:
            completed_stages = list(state.get("completed_stages") or [])
            for stage in [str(gate), "final"]:
                if stage not in completed_stages:
                    completed_stages.append(stage)
            write_completed_state(out, source=state.get("source"), completed_stages=completed_stages)
            print("Final reports validated after revision. Pipeline completed.")
            return 0
        if has_quality_repair_plan(out):
            repair_args = argparse.Namespace(
                source=state.get("source"),
                config=args.config or (Path(state["config_path"]) if state.get("config_path") else None),
                manual_segments=Path(state["manual_segments"]) if state.get("manual_segments") else None,
                agent_gates_list=state.get("agent_gates") or [],
                writer=state.get("writer"),
            )
            pause_for_report_quality_repair(out, repair_args, list(state.get("completed_stages") or []), str(state.get("writer") or "agent"))
            return 1
        print_validation_feedback(
            validation,
            next_hint="请继续修复 agent_quality_repair_plan.json 中列出的 allowed_write_paths，然后再次运行 validate --phase final 或 resume。",
        )
        return 1
    print(f"Unsupported blocked gate: {gate}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conference-report")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_cfg = sub.add_parser("init-config")
    init_cfg.add_argument("path", type=Path)
    add_profile_option(init_cfg)

    auth = sub.add_parser("auth")
    auth_sub = auth.add_subparsers(dest="auth_cmd", required=True)
    auth_set = auth_sub.add_parser("set")
    auth_set.add_argument("provider", choices=["openai"])
    auth_status = auth_sub.add_parser("status")
    auth_status.add_argument("provider", choices=["openai"])
    auth_delete = auth_sub.add_parser("delete")
    auth_delete.add_argument("provider", choices=["openai"])

    build = sub.add_parser("build")
    build.add_argument("source")
    add_common(build)
    add_profile_option(build)
    build.add_argument("--manual-segments", type=Path)
    build.add_argument("--agent-gates", default="", help="Comma-separated agent gates to pause on, e.g. dedupe,report.")
    add_writer_options(build, build=True)

    status = sub.add_parser("status")
    status.add_argument("--out", type=Path, required=True)

    resume = sub.add_parser("resume")
    resume.add_argument("--out", type=Path, required=True)
    resume.add_argument("--config", type=Path)

    for name in ["ingest", "asr", "slides", "dedupe", "segment", "report", "validate"]:
        cmd = sub.add_parser(name)
        if name in {"ingest", "asr"}:
            cmd.add_argument("source")
        add_common(cmd)
        if name == "segment":
            cmd.add_argument("--manual-segments", type=Path)
        if name == "report":
            add_writer_options(cmd)
        if name == "validate":
            cmd.add_argument(
                "--phase",
                choices=["evidence", "dedupe-review", "agent-tasks", "report-quality", "final"],
                default="evidence",
            )

    args = parser.parse_args(argv)
    if args.cmd == "init-config":
        write_default_config(args.path, profile=args.profile)
        print(f"Wrote {args.path}")
        print(f"Config profile: {args.profile}")
        return 0
    if args.cmd == "auth":
        if args.auth_cmd == "set":
            set_secret_interactive(args.provider)
        elif args.auth_cmd == "delete":
            delete_secret(args.provider)
        elif args.auth_cmd == "status":
            status = credential_status(args.provider)
            source = f" via {status.source}" if status.source else ""
            detail = f" ({status.detail})" if status.detail else ""
            print(f"{status.provider}: {'available' if status.available else 'missing'}{source}{detail}")
            return 0 if status.available else 1
        return 0

    out = args.out.resolve()

    if args.cmd == "status":
        print(format_state_for_human(status_state(out)))
        return 0

    if args.cmd == "build":
        cfg = prepare_build_config(args, out)
    else:
        if args.cmd == "resume" and args.config is None:
            args.config = config_path_from_state(out)
        cfg = load_config(args.config)

    if args.cmd in PIPELINE_COMMANDS:
        state = read_pipeline_state(out)
        if is_waiting(state):
            print(blocked_command_message(args.cmd, state))
            return 1

    if args.cmd == "resume":
        return resume_pipeline(out, cfg, args)

    if args.cmd == "ingest":
        ingest(args.source, out, cookies_from_browser=args.cookies_from_browser)
    elif args.cmd == "asr":
        run_asr(args.source, out, cfg, cookies_from_browser=args.cookies_from_browser)
    elif args.cmd == "slides":
        extract_slides(out, cfg)
    elif args.cmd == "dedupe":
        dedupe_slides(out, cfg)
    elif args.cmd == "segment":
        segment(out, cfg, manual_segments=args.manual_segments)
    elif args.cmd == "report":
        generate_reports(out, cfg, writer=selected_writer(args))
    elif args.cmd == "validate":
        result = validate_run(out, phase=args.phase)
        if args.phase == "agent-tasks":
            refresh_report_gate_after_agent_tasks(out, result=result)
        if args.phase in {"report-quality", "final"} and not result["ok"] and has_quality_repair_plan(out):
            state = read_pipeline_state(out)
            source = state.get("source") if state else None
            config_path = args.config or (Path(state["config_path"]) if state and state.get("config_path") else None)
            manual_segments = Path(state["manual_segments"]) if state and state.get("manual_segments") else None
            agent_gates = state.get("agent_gates") if state else []
            writer = state.get("writer") if state else "agent"
            completed_stages = list(state.get("completed_stages") or []) if state else []
            if "report_quality" not in completed_stages:
                completed_stages.append("report_quality")
            repair_args = argparse.Namespace(
                source=source,
                config=config_path,
                manual_segments=manual_segments,
                agent_gates_list=agent_gates or [],
                writer=writer,
            )
            pause_for_report_quality_repair(out, repair_args, completed_stages, str(writer or "agent"))
        print("OK" if result["ok"] else "FAILED")
        return 0 if result["ok"] else 1
    elif args.cmd == "build":
        args.agent_gates_list = parse_agent_gates(args.agent_gates)
        manifest = {"source": args.source, "steps": []}
        ingest(args.source, out, cookies_from_browser=args.cookies_from_browser)
        manifest["steps"].append("ingest")
        run_asr(args.source, out, cfg, cookies_from_browser=args.cookies_from_browser)
        manifest["steps"].append("asr")
        extract_slides(out, cfg)
        manifest["steps"].append("slides")
        dedupe_manifest = dedupe_slides(out, cfg)
        manifest["steps"].append("dedupe")
        if "dedupe" in args.agent_gates_list and int(dedupe_manifest.get("semantic_review_task_count", 0)) > 0:
            state = write_waiting_state(
                out,
                source=args.source,
                completed_stages=list(manifest["steps"]),
                blocked_gate="dedupe_review",
                config_path=args.config,
                writer=selected_writer(args, build=True),
                manual_segments=args.manual_segments,
                agent_gates=args.agent_gates_list,
            )
            manifest["waiting_for_agent"] = "dedupe_review"
            write_json(out / "manifest.json", manifest)
            print(format_state_for_human(state))
            return 0
        segment(out, cfg, manual_segments=args.manual_segments)
        manifest["steps"].append("segment")
        generate_reports(out, cfg, writer=selected_writer(args, build=True))
        manifest["steps"].append("report")
        reports_manifest = {}
        reports_manifest_path = out / "reports_manifest.json"
        if reports_manifest_path.exists():
            reports_manifest = read_json(reports_manifest_path)
        if reports_manifest.get("writer_mode") == "agent":
            validation_phase = "agent-tasks"
        elif reports_manifest.get("writer_mode") == "openai":
            validation_phase = "final"
        else:
            validation_phase = "evidence"
        validation = validate_run(out, phase=validation_phase)
        manifest["steps"].append("validate")
        manifest["validation_phase"] = validation_phase
        manifest["validation_ok"] = validation["ok"]
        write_json(out / "manifest.json", manifest)
        if validation["ok"] and reports_manifest.get("writer_mode") == "agent":
            pause_for_report_agent(out, args, list(manifest["steps"]), selected_writer(args, build=True))
            return 0
        return 0 if validation["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
