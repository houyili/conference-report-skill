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
from .utils import write_json
from .validate import validate_run


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--cookies-from-browser")


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
    build.add_argument("--dry-run-report", action="store_true")

    for name in ["ingest", "asr", "slides", "dedupe", "segment", "report", "validate"]:
        cmd = sub.add_parser(name)
        if name in {"ingest", "asr"}:
            cmd.add_argument("source")
        add_common(cmd)
        if name == "segment":
            cmd.add_argument("--manual-segments", type=Path)
        if name == "report":
            cmd.add_argument("--dry-run", action="store_true")

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
        generate_reports(out, cfg, dry_run=args.dry_run)
    elif args.cmd == "validate":
        result = validate_run(out)
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
        generate_reports(out, cfg, dry_run=args.dry_run_report)
        manifest["steps"].append("report")
        validation = validate_run(out)
        manifest["steps"].append("validate")
        manifest["validation_ok"] = validation["ok"]
        write_json(out / "manifest.json", manifest)
        return 0 if validation["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
