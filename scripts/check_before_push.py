#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> int:
    print("+ " + " ".join(shlex.quote(part) for part in cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def main() -> int:
    status = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    if status != 0:
        return status

    validator = os.environ.get("CONFERENCE_REPORT_SKILL_VALIDATOR")
    if validator:
        validator_path = Path(validator).expanduser()
        status = run([sys.executable, str(validator_path), str(ROOT / "skills" / "conference-report")])
        if status != 0:
            return status
    else:
        print("Skipping skill validator; set CONFERENCE_REPORT_SKILL_VALIDATOR to enable it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
