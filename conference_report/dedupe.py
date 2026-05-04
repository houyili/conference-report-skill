from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

from .embeddings import run_semantic_dedupe_artifacts
from .utils import ensure_dir, extract_time_from_name, format_time, list_pngs, parse_time_seconds, timeline_lines, write_json


@dataclass
class Slide:
    path: Path
    time: str
    seconds: float
    ahash: int
    small: Image.Image


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def average_hash(img: Image.Image, size: int = 16) -> int:
    tiny = img.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = list(tiny.getdata())
    avg = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= avg)
    return value


def load_slide(path: Path, compare_width: int = 320) -> Slide:
    time = extract_time_from_name(path)
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        scale = compare_width / rgb.width
        small = rgb.resize((compare_width, round(rgb.height * scale)), Image.Resampling.LANCZOS)
        return Slide(path=path, time=time, seconds=parse_time_seconds(time), ahash=average_hash(rgb), small=small)


def diff_stats(a: Image.Image, b: Image.Image) -> tuple[float, float]:
    diff = ImageChops.difference(a, b).convert("L")
    stat = ImageStat.Stat(diff)
    mean = stat.mean[0]
    changed = sum(1 for pixel in diff.getdata() if pixel > 18) / (diff.width * diff.height)
    return mean, changed


def is_duplicate(prev: Slide, curr: Slide, cfg: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    mean, changed = diff_stats(prev.small, curr.small)
    hash_distance = hamming(prev.ahash, curr.ahash)
    duplicate = (
        mean <= float(cfg["dedupe"].get("mean_threshold", 1.2))
        and changed <= float(cfg["dedupe"].get("changed_threshold", 0.006))
        and hash_distance <= int(cfg["dedupe"].get("hash_threshold", 6))
    )
    return duplicate, {"mean_abs_diff": round(mean, 4), "changed_ratio": round(changed, 6), "ahash_hamming": hash_distance}


def final_end_seconds(out_dir: Path) -> float:
    rows = timeline_lines(out_dir / "asr" / "timeline.txt")
    slide_paths = list_pngs(out_dir / "slides_original")
    candidates = []
    if rows:
        candidates.append(rows[-1]["seconds"])
    if slide_paths:
        candidates.append(parse_time_seconds(extract_time_from_name(slide_paths[-1])) + 5)
    return max(candidates or [0.0])


def build_intervals(rows: list[dict[str, Any]], final_end: float) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        seconds = parse_time_seconds(row["time"])
        if current is None or row["cluster_id"] != current["cluster_id"]:
            if current is not None:
                current["end_seconds"] = seconds
                intervals.append(current)
            current = {
                "cluster_id": row["cluster_id"],
                "representative_time": row["kept_time"],
                "representative_path": row["kept_path"],
                "start_seconds": seconds,
                "source_times": [row["time"]],
                "source_paths": [row["original_path"]],
            }
        else:
            current["source_times"].append(row["time"])
            current["source_paths"].append(row["original_path"])
    if current is not None:
        current["end_seconds"] = max(final_end, current["start_seconds"])
        intervals.append(current)
    for idx, interval in enumerate(intervals, start=1):
        interval["interval_index"] = idx
        interval["start_time"] = format_time(interval["start_seconds"])
        interval["end_time"] = format_time(interval["end_seconds"])
        interval["duration_seconds"] = round(interval["end_seconds"] - interval["start_seconds"], 3)
    return intervals


def build_groups(rows: list[dict[str, Any]], intervals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = groups.setdefault(row["cluster_id"], {
            "cluster_id": row["cluster_id"],
            "representative_time": row["kept_time"],
            "representative_path": row["kept_path"],
            "all_source_times": [],
            "duplicate_times": [],
            "all_intervals": [],
            "main_interval": None,
        })
        group["all_source_times"].append(row["time"])
        if row["decision"] == "duplicate":
            group["duplicate_times"].append(row["time"])
    for interval in intervals:
        groups[interval["cluster_id"]]["all_intervals"].append({
            "start_time": interval["start_time"],
            "end_time": interval["end_time"],
            "duration_seconds": interval["duration_seconds"],
            "source_times": interval["source_times"],
        })
    for group in groups.values():
        if group["all_intervals"]:
            group["main_interval"] = max(group["all_intervals"], key=lambda item: item["duration_seconds"])
    return sorted(groups.values(), key=lambda group: parse_time_seconds(group["representative_time"]))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_intervals_csv(path: Path, intervals: list[dict[str, Any]]) -> None:
    fields = ["interval_index", "cluster_id", "representative_time", "start_time", "end_time", "duration_seconds", "representative_path", "source_times"]
    rows = [{**{field: item.get(field) for field in fields}, "source_times": ";".join(item["source_times"])} for item in intervals]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_review_html(path: Path, rows: list[dict[str, Any]]) -> None:
    duplicate_rows = [row for row in rows if row["decision"] == "duplicate"]
    parts = [
        "<!doctype html><meta charset='utf-8'><title>Slide Dedupe Review</title>",
        "<style>body{font-family:system-ui,sans-serif;margin:24px} table{border-collapse:collapse;width:100%} td,th{border:1px solid #ddd;padding:6px;vertical-align:top} img{max-width:360px}</style>",
        f"<h1>Slide Dedupe Review</h1><p>Duplicate candidates: {len(duplicate_rows)}. Originals were not modified.</p>",
        "<table><tr><th>Duplicate</th><th>Kept</th><th>Metrics</th><th>Duplicate</th><th>Kept</th></tr>",
    ]
    for row in duplicate_rows:
        parts.append(
            f"<tr><td>{row['time']}</td><td>{row['kept_time']}</td>"
            f"<td>mean={row['mean_abs_diff']}<br>changed={row['changed_ratio']}<br>hash={row['ahash_hamming']}</td>"
            f"<td><img src='{Path(row['original_path']).resolve().as_uri()}'></td>"
            f"<td><img src='{Path(row['kept_path']).resolve().as_uri()}'></td></tr>"
        )
    parts.append("</table>")
    path.write_text("\n".join(parts), encoding="utf-8")


def dedupe_slides(out_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    source_dir = out_dir / "slides_original"
    dedup_dir = ensure_dir(out_dir / "slides_dedup")
    provenance_dir = ensure_dir(out_dir / "dedupe")
    source_paths = list_pngs(source_dir)
    if not source_paths:
        raise SystemExit(f"No slides found in {source_dir}")

    rows: list[dict[str, Any]] = []
    kept: list[Slide] = []
    cluster_by_time: dict[str, str] = {}
    lookback = int(cfg["dedupe"].get("lookback_kept", 8))
    for path in source_paths:
        current = load_slide(path)
        duplicate = False
        metrics: dict[str, Any] = {"mean_abs_diff": "", "changed_ratio": "", "ahash_hamming": ""}
        kept_ref: Slide | None = None
        for candidate in reversed(kept[-lookback:]):
            duplicate, metrics = is_duplicate(candidate, current, cfg)
            if duplicate:
                kept_ref = candidate
                break
        if not duplicate:
            kept_ref = current
            kept.append(current)
            cluster_by_time[current.time] = f"slide-{len(kept):04d}"
            shutil.copy2(path, dedup_dir / path.name)
        assert kept_ref is not None
        rows.append({
            "cluster_id": cluster_by_time.get(kept_ref.time, kept_ref.time),
            "time": current.time,
            "decision": "duplicate" if duplicate else "keep",
            "kept_time": kept_ref.time,
            "original_path": str(path.resolve()),
            "kept_path": str(kept_ref.path.resolve()),
            **metrics,
        })

    intervals = build_intervals(rows, final_end_seconds(out_dir))
    groups = build_groups(rows, intervals)
    write_csv(provenance_dir / "dedup_report.csv", rows)
    write_json(provenance_dir / "dedup_report.json", rows)
    write_intervals_csv(out_dir / "slide_intervals.csv", intervals)
    write_json(out_dir / "slide_intervals.json", intervals)
    write_json(out_dir / "dedup_groups.json", groups)
    write_review_html(provenance_dir / "dedup_review.html", rows)
    semantic_manifest = run_semantic_dedupe_artifacts(out_dir, cfg, source_paths, rows)
    manifest = {
        "original_count": len(source_paths),
        "kept_count": len(kept),
        "duplicate_count": len(source_paths) - len(kept),
        "slides_dedup": str(dedup_dir.resolve()),
        **semantic_manifest,
    }
    write_json(out_dir / "dedupe_manifest.json", manifest)
    return manifest
