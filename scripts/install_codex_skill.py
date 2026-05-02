#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from install_agent_skill import DEFAULT_SKILL_NAME, default_source, install_skill


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper for installing the bundled skill into a user-specified Codex skills root."
    )
    parser.add_argument("command", choices=["install", "upgrade"], nargs="?", default="install")
    parser.add_argument(
        "--target-dir",
        type=Path,
        required=True,
        help="Codex skills root directory. The skill is installed as TARGET_DIR/conference-report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    installed = install_skill(
        default_source(DEFAULT_SKILL_NAME),
        [args.target_dir],
        DEFAULT_SKILL_NAME,
        upgrade=args.command == "upgrade",
    )
    verb = "Upgraded" if args.command == "upgrade" else "Installed"
    print(f"{verb} {DEFAULT_SKILL_NAME} skill to {installed[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
