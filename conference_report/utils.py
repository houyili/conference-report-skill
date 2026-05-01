from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


TIME_RE = re.compile(r"\[(\d\d:\d\d:\d\d\.\d\d\d)\]")


def run(cmd: list[str], *, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(str(part) for part in cmd), flush=True)
    return subprocess.run(cmd, check=check, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def find_tool(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    suffix = ".exe" if sys.platform.startswith("win") else ""
    bin_name = "Scripts" if sys.platform.startswith("win") else "bin"
    local_bins = [
        Path(sys.prefix) / bin_name,
        Path(sys.executable).parent,
        Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else None,
        Path(sys.executable).resolve().parent,
    ]
    for directory in local_bins:
        if directory is None:
            continue
        candidate = directory / f"{name}{suffix}"
        if candidate.exists():
            return str(candidate.resolve())
    return None


def require_tool(name: str) -> str:
    path = find_tool(name)
    if path is None:
        raise SystemExit(f"Missing required command-line tool: {name}")
    return path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_time_seconds(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip().strip("[]")
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = "0", parts[0], parts[1]
    else:
        raise ValueError(f"Invalid timestamp: {value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def extract_time_from_name(path: Path) -> str:
    match = TIME_RE.search(path.name)
    if match:
        return match.group(1)
    return path.stem


def slugify(text: str, *, fallback: str = "item") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    return slug[:120] or fallback


def list_pngs(path: Path) -> list[Path]:
    return sorted(path.glob("*.png"), key=lambda p: parse_time_seconds(extract_time_from_name(p)))


def timeline_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"\[(\d\d:\d\d:\d\d\.\d\d\d)\]\s*(.*)", line)
        if match:
            rows.append({"time": match.group(1), "seconds": parse_time_seconds(match.group(1)), "text": match.group(2).strip()})
    return rows


def subset_timeline(path: Path, start: float, end: float) -> list[dict[str, Any]]:
    return [row for row in timeline_lines(path) if start <= row["seconds"] < end]


def write_timeline(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    path.write_text("".join(f"[{row['time']}] {row['text']}\n" for row in rows), encoding="utf-8")


def media_duration_from_timeline(path: Path) -> float:
    rows = timeline_lines(path)
    return rows[-1]["seconds"] if rows else 0.0
