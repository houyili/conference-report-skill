#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_NAME = "conference-report"
LOCAL_CONFIG_DIR = ".local"
CLI_PATH_FILE = "cli-path.txt"


def default_source(skill_name: str = DEFAULT_SKILL_NAME) -> Path:
    return ROOT / "skills" / skill_name


def write_local_cli_path(target: Path, cli_path: Path | None) -> None:
    if cli_path is None:
        return
    local_dir = target / LOCAL_CONFIG_DIR
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = cli_path.expanduser().resolve(strict=False)
    (local_dir / CLI_PATH_FILE).write_text(f"{local_path}\n", encoding="utf-8")


def install_skill(
    source: Path,
    target_dirs: list[Path],
    skill_name: str,
    *,
    upgrade: bool,
    cli_path: Path | None = None,
) -> list[Path]:
    if not target_dirs:
        raise ValueError("At least one --target-dir must be provided.")
    source = source.expanduser().resolve()
    if not (source / "SKILL.md").exists():
        raise FileNotFoundError(f"Missing skill source with SKILL.md: {source}")

    installed: list[Path] = []
    for target_root in target_dirs:
        target_root = target_root.expanduser()
        target = target_root / skill_name
        if target.exists():
            if not upgrade:
                raise FileExistsError(f"{target} already exists. Use the upgrade command to replace it.")
            shutil.rmtree(target)
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        write_local_cli_path(target, cli_path)
        installed.append(target)
    return installed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or upgrade an agent skill into user-specified global skill directories."
    )
    parser.add_argument("command", choices=["install", "upgrade"])
    parser.add_argument("--skill-name", default=DEFAULT_SKILL_NAME)
    parser.add_argument("--source", type=Path, help="Skill source directory. Defaults to this checkout's bundled skill.")
    parser.add_argument(
        "--target-dir",
        type=Path,
        action="append",
        required=True,
        help="Agent skills root directory. Repeat for Codex, Claude Code, Antigravity, OpenClaw, or other agents.",
    )
    parser.add_argument(
        "--cli-path",
        type=Path,
        help="Installed conference-report CLI path to record in the installed skill copy for agent runtimes whose PATH cannot see it.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = args.source or default_source(args.skill_name)
    installed = install_skill(
        source,
        args.target_dir,
        args.skill_name,
        upgrade=args.command == "upgrade",
        cli_path=args.cli_path,
    )
    verb = "Upgraded" if args.command == "upgrade" else "Installed"
    for path in installed:
        print(f"{verb} {args.skill_name} skill to {path}")
        if args.cli_path is not None:
            print(f"Recorded CLI path in {path / LOCAL_CONFIG_DIR / CLI_PATH_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
