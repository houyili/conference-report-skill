#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "conference-report"


def main() -> int:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    source = ROOT / "skills" / SKILL_NAME
    target = codex_home / "skills" / SKILL_NAME
    if not source.exists():
        raise SystemExit(f"Missing skill source: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    print(f"Installed {SKILL_NAME} skill to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

