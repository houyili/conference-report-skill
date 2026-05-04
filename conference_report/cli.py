from __future__ import annotations

import argparse
from pathlib import Path

from .auth import credential_status, delete_secret, set_secret_interactive
from .asr import run_asr
from .config import load_config, write_default_config
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
from .report import generate_reports
from .segment import segment
from .slides import extract_slides
from .utils import read_json, write_json
from .validate import validate_run


WRITER_CHOICES = ["auto", "agent", "openai", "evidence"]
PIPELINE_COMMANDS = {"build", "ingest", "asr", "slides", "dedupe", "segment", "report"}


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--cookies-from-browser")


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
            "agent_slide_cognition_tasks.json",
            "agent_qa_tasks.json",
            "agent_report_tasks.json",
            "agent_grounding_tasks.json",
        ]
    reports_manifest = read_json(reports_manifest_path)
    task_manifests = reports_manifest.get("task_manifests") or {}
    if isinstance(task_manifests, dict):
        return [display_path(str(path)) for path in task_manifests.values()]
    return [
        "agent_slide_cognition_tasks.json",
        "agent_qa_tasks.json",
        "agent_report_tasks.json",
        "agent_grounding_tasks.json",
    ]


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
    state["next_allowed_command"] = f"conference-report validate --out {out} --phase final"
    write_json(out / "pipeline_state.json", state)
    print(format_state_for_human(state))


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
        print_validation_feedback(
            validation,
            next_hint="请只修复失败 task 的 allowed_write_paths，然后再次运行 validate --phase final 或 resume。",
        )
        return 1
    print(f"Unsupported blocked gate: {gate}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conference-report")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_cfg = sub.add_parser("init-config")
    init_cfg.add_argument("path", type=Path)

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
            cmd.add_argument("--phase", choices=["evidence", "dedupe-review", "agent-tasks", "final"], default="evidence")

    args = parser.parse_args(argv)
    if args.cmd == "init-config":
        write_default_config(args.path)
        print(f"Wrote {args.path}")
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
        print(format_state_for_human(read_pipeline_state(out)))
        return 0

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
