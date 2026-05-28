#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agent_skill_roots import candidate_skill_root_entries

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


def read_local_cli_path(target: Path) -> Path | None:
    path = target / LOCAL_CONFIG_DIR / CLI_PATH_FILE
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return Path(value).expanduser() if value else None


def discover_cli_path() -> Path | None:
    found = shutil.which("conference-report")
    return Path(found) if found else None


def candidate_skill_roots(home: Path, env: dict[str, str]) -> list[tuple[str, Path, str]]:
    return candidate_skill_root_entries(home, env)


def installed_skill_roots(
    home: Path,
    env: dict[str, str],
    skill_name: str = DEFAULT_SKILL_NAME,
) -> list[tuple[str, Path, str]]:
    return [
        (label, root, source)
        for label, root, source in candidate_skill_roots(home, env)
        if (root / skill_name / "SKILL.md").exists()
    ]


def prompt_for_target_dirs(command: str, skill_name: str) -> list[Path]:
    if command == "upgrade":
        candidates = installed_skill_roots(Path.home(), os.environ, skill_name)
        intro = f"Found installed {skill_name} skill copies:"
    else:
        candidates = candidate_skill_roots(Path.home(), os.environ)
        intro = "Found candidate agent skill roots:"

    if candidates:
        print(f"\n{intro}")
        for index, (label, root, source) in enumerate(candidates, start=1):
            target = root / skill_name if command == "upgrade" else root
            print(f"  {index}. {label}: {target} ({source})")
        print("Choose one or more numbers separated by commas, or type another skills root path.")
        answer = input("Target [default 1]: ").strip()
        if not answer:
            return [candidates[0][1]]
        selected: list[Path] = []
        pieces = [piece.strip() for piece in answer.split(",") if piece.strip()]
        if pieces and all(piece.isdigit() for piece in pieces):
            for piece in pieces:
                index = int(piece)
                if not 1 <= index <= len(candidates):
                    raise SystemExit(f"Invalid selection: {piece}")
                selected.append(candidates[index - 1][1])
            return selected
        return [Path(answer).expanduser()]

    if command == "upgrade":
        print(f"No installed {skill_name} skill copies were found in known local agent roots.")
    else:
        print("No existing agent skill roots were found.")
    answer = input("Type the agent skills root path: ").strip()
    if not answer:
        raise SystemExit("No target directory selected.")
    return [Path(answer).expanduser()]


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
        target_cli_path = cli_path or read_local_cli_path(target)
        if target.exists():
            if not upgrade:
                raise FileExistsError(f"{target} already exists. Use the upgrade command to replace it.")
            shutil.rmtree(target)
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        write_local_cli_path(target, target_cli_path)
        installed.append(target)
    return installed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or upgrade an agent skill into user-specified global skill directories."
    )
    parser.add_argument("command", choices=["install", "upgrade"])
    parser.add_argument(
        "target_hint",
        nargs="?",
        help="Optional '-' to force interactive target selection. Prefer --target-dir for non-interactive use.",
    )
    parser.add_argument("--skill-name", default=DEFAULT_SKILL_NAME)
    parser.add_argument("--source", type=Path, help="Skill source directory. Defaults to this checkout's bundled skill.")
    parser.add_argument(
        "--target-dir",
        type=Path,
        action="append",
        help="Agent skills root directory. Repeat for Codex, Claude Code, Antigravity, OpenClaw, or other agents. If omitted, the script interactively recommends local targets.",
    )
    parser.add_argument(
        "--cli-path",
        type=Path,
        help="Installed conference-report CLI path to record in the installed skill copy for agent runtimes whose PATH cannot see it.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.target_hint and args.target_hint != "-":
        raise SystemExit("Unexpected positional target. Use --target-dir PATH, or '-' for interactive selection.")
    source = args.source or default_source(args.skill_name)
    target_dirs = args.target_dir or prompt_for_target_dirs(args.command, args.skill_name)
    cli_path = args.cli_path or discover_cli_path()
    try:
        installed = install_skill(
            source,
            target_dirs,
            args.skill_name,
            upgrade=args.command == "upgrade",
            cli_path=cli_path,
        )
    except OSError as exc:
        targets = ", ".join(str(path.expanduser() / args.skill_name) for path in target_dirs)
        raise SystemExit(
            f"Could not modify installed skill target(s): {targets}. "
            "Check filesystem permissions or run this command from an environment allowed to edit the selected agent skills root. "
            f"Original error: {exc}"
        ) from None
    verb = "Upgraded" if args.command == "upgrade" else "Installed"
    for path in installed:
        print(f"{verb} {args.skill_name} skill to {path}")
        recorded_cli = read_local_cli_path(path)
        if recorded_cli is not None:
            print(f"Recorded CLI path in {path / LOCAL_CONFIG_DIR / CLI_PATH_FILE}")
        else:
            print(
                "Warning: no conference-report CLI path was recorded. "
                "Install the Python package or rerun with --cli-path /absolute/path/to/conference-report."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
