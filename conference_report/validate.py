from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .utils import parse_time_seconds, read_json, timeline_lines, write_json


def validate_run(out_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    timeline = out_dir / "asr" / "timeline.txt"
    if not timeline.exists():
        errors.append("Missing asr/timeline.txt")
    else:
        rows = timeline_lines(timeline)
        if not rows:
            errors.append("ASR timeline is empty")
        if any(rows[i]["seconds"] > rows[i + 1]["seconds"] for i in range(len(rows) - 1)):
            errors.append("ASR timeline is not monotonic")

    for required in ["slides_original", "slides_dedup", "slide_intervals.json", "segmentation/talks.json"]:
        if not (out_dir / required).exists():
            errors.append(f"Missing {required}")

    if (out_dir / "slide_intervals.json").exists():
        intervals = read_json(out_dir / "slide_intervals.json")
        if any(item["start_seconds"] > item["end_seconds"] for item in intervals):
            errors.append("Slide interval has start > end")

    if (out_dir / "segmentation" / "talks.json").exists():
        talks = read_json(out_dir / "segmentation" / "talks.json")
        for talk in talks:
            if talk.get("reportable"):
                if not talk.get("slug"):
                    errors.append(f"Reportable talk missing slug: {talk.get('talk_id')}")
                elif not (out_dir / "talks" / talk["slug"]).exists():
                    warnings.append(f"Reportable talk not packaged: {talk.get('talk_id')}")

    for report in (out_dir / "reports").glob("*.md") if (out_dir / "reports").exists() else []:
        text = report.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
            image = report.parent / unquote(match.group(1))
            if not image.exists():
                warnings.append(f"Broken image in {report.name}: {match.group(1)}")

    result = {"ok": not errors, "errors": errors, "warnings": warnings}
    write_json(out_dir / "validation.json", result)
    return result
