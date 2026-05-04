from __future__ import annotations

import argparse
from pathlib import Path

from .auth import credential_status, delete_secret, set_secret_interactive
from .asr import run_asr
from .config import load_config, write_default_config
from .dedupe import dedupe_slides
from .ingest import ingest
from .report import generate_reports
from .segment import segment
from .slides import extract_slides
from .utils import read_json, write_json
from .validate import validate_run


WRITER_CHOICES = ["auto", "agent", "openai", "evidence"]


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
    add_writer_options(build, build=True)

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
            cmd.add_argument("--phase", choices=["evidence", "agent-tasks", "final"], default="evidence")

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

    cfg = load_config(args.config)
    out = args.out.resolve()

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
        manifest = {"source": args.source, "steps": []}
        ingest(args.source, out, cookies_from_browser=args.cookies_from_browser)
        manifest["steps"].append("ingest")
        run_asr(args.source, out, cfg, cookies_from_browser=args.cookies_from_browser)
        manifest["steps"].append("asr")
        extract_slides(out, cfg)
        manifest["steps"].append("slides")
        dedupe_slides(out, cfg)
        manifest["steps"].append("dedupe")
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
        return 0 if validation["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
