#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import stat
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def install_pre_push_hook(repo_root: Path, python_executable: Path) -> Path:
    repo_root = repo_root.expanduser()
    hooks_dir = repo_root / ".git" / "hooks"
    check_script = repo_root / "scripts" / "check_before_push.py"
    if not hooks_dir.exists():
        raise FileNotFoundError(f"Missing git hooks directory: {hooks_dir}")
    if not check_script.exists():
        raise FileNotFoundError(f"Missing check script: {check_script}")

    hook_path = hooks_dir / "pre-push"
    hook_path.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(str(python_executable))} {shlex.quote(str(check_script))}\n",
        encoding="utf-8",
    )
    mode = hook_path.stat().st_mode
    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install repository-local git hooks for development validation.")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    hook_path = install_pre_push_hook(args.repo_root, args.python)
    print(f"Installed pre-push hook to {hook_path}")
    print("Set CONFERENCE_REPORT_SKILL_VALIDATOR to run an additional skill validator before push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
