from __future__ import annotations

import csv
import re
import shutil
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .utils import ensure_dir, format_time, parse_time_seconds, read_json, slugify, subset_timeline, timeline_lines, write_json, write_timeline


BREAK_KEYWORDS = ("break", "coffee", "poster", "lunch", "registration", "opening remarks", "closing remarks")
TALK_TYPES = ("oral", "keynote", "invited", "panel", "talk", "presentation", "spotlight")
TITLE_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "of", "on", "or", "the", "to",
    "under", "via", "with", "without",
}
TOKEN_ALIASES = {
    "hubble": {"hobbul"},
    "hobbul": {"hubble"},
    "memorization": {"memory"},
    "memory": {"memorization"},
    "suite": {"suit"},
    "suit": {"suite"},
    "llms": {"llm", "lrm"},
    "llm": {"llms", "lrm"},
    "experts": {"expert"},
}
TRANSITION_RE = re.compile(
    r"\b(first|second|third|fourth|last|next)\s+(paper|presentation|presenter|presenters|talk)|"
    r"\b(paper|work)\s+titled?\b|\bwill\s+present\b|\blet'?s\s+thank\b",
    re.I,
)


def is_break(title: str, event_type: str = "") -> bool:
    text = f"{title} {event_type}".lower()
    return any(keyword in text for keyword in BREAK_KEYWORDS)


def is_reportable(title: str, event_type: str = "") -> bool:
    text = f"{title} {event_type}".lower()
    if is_break(title, event_type):
        return False
    return any(kind in text for kind in TALK_TYPES) or not event_type


def parse_clock(value: str) -> float | None:
    match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", value)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    return hour * 3600 + minute * 60 + second


def parse_time_range(value: str) -> tuple[float, float] | None:
    match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?)", value)
    if not match:
        return None
    start = parse_clock(match.group(1))
    end = parse_clock(match.group(2))
    if start is None or end is None:
        return None
    if end <= start:
        end += 24 * 3600
    return start, end


def event_type_from_href(href: str) -> str:
    parts = [part for part in href.split("/") if part]
    if len(parts) >= 3 and parts[0] == "virtual":
        return parts[2]
    return "talk"


def parse_track_schedule_cards(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in soup.select(".track-schedule-card"):
        title_el = card.select_one("h5 a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title:
            continue
        time_el = card.select_one(".track-pad, .btn-spacer")
        time_range = parse_time_range(time_el.get_text(" ", strip=True) if time_el else "")
        href = title_el.get("href", "")
        speaker_el = card.select_one("p.text-muted")
        speakers = []
        if speaker_el:
            speakers = [part.strip() for part in re.split(r"\s*[⋅·]\s*", speaker_el.get_text(" ", strip=True)) if part.strip()]
        abstract_el = card.select_one(".abstract")
        item: dict[str, Any] = {
            "title": title,
            "type": event_type_from_href(href),
            "speakers": speakers,
            "href": href,
        }
        if time_range:
            item["schedule_clock"], item["schedule_end_clock"] = time_range
        if abstract_el:
            item["abstract"] = abstract_el.get_text(" ", strip=True)
        rows.append(item)
    return rows


def parse_schedule_html(page: Path) -> list[dict[str, Any]]:
    if not page.exists():
        return []
    soup = BeautifulSoup(page.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    card_rows = parse_track_schedule_cards(soup)
    if card_rows:
        return card_rows
    rows: list[dict[str, Any]] = []
    for row in soup.select(".schedule-row, tr"):
        time_el = row.select_one(".schedule-time")
        name_el = row.select_one(".schedule-event-name")
        type_el = row.select_one(".schedule-event-type")
        if not time_el or not name_el:
            continue
        start = parse_clock(time_el.get_text(" ", strip=True))
        if start is None:
            continue
        title = name_el.get_text(" ", strip=True)
        event_type = type_el.get_text(" ", strip=True) if type_el else ""
        rows.append({"title": title, "type": event_type, "schedule_clock": start, "speakers": []})
    return rows


def load_manual_segments(path: Path) -> list[dict[str, Any]]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("talks", data if isinstance(data, list) else [])


def normalize_schedule(schedule: list[dict[str, Any]], first_content: float, final_end: float) -> list[dict[str, Any]]:
    if not schedule:
        return []
    first_clock = schedule[0].get("schedule_clock")
    if first_clock is None:
        return schedule
    normalized = []
    for idx, item in enumerate(schedule):
        start = first_content + (float(item["schedule_clock"]) - float(first_clock))
        if item.get("schedule_end_clock") is not None:
            end = first_content + (float(item["schedule_end_clock"]) - float(first_clock))
        else:
            next_clock = schedule[idx + 1].get("schedule_clock") if idx + 1 < len(schedule) else None
            end = final_end if next_clock is None else first_content + (float(next_clock) - float(first_clock))
        normalized.append({**item, "schedule_start": format_time(max(0, start)), "schedule_end": format_time(max(start, end))})
    return normalized


def token_variants(token: str) -> set[str]:
    variants = {token}
    if token.endswith("s") and len(token) > 3:
        variants.add(token[:-1])
    variants.update(TOKEN_ALIASES.get(token, set()))
    return variants


def content_token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        if raw in TITLE_STOPWORDS or len(raw) < 2:
            continue
        tokens.update(token_variants(raw))
    return tokens


def title_tokens(title: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", title.lower()):
        if raw in TITLE_STOPWORDS or len(raw) < 2:
            continue
        for variant in token_variants(raw):
            if variant not in seen:
                seen.add(variant)
                tokens.append(variant)
    return tokens


def transcript_context(transcript: list[dict[str, Any]], index: int, seconds: float = 30.0) -> str:
    start = transcript[index]["seconds"]
    chunks = []
    for row in transcript[index:]:
        if row["seconds"] - start > seconds:
            break
        chunks.append(str(row["text"]))
    return " ".join(chunks)


def find_title_alignment(item: dict[str, Any], transcript: list[dict[str, Any]], earliest: float) -> dict[str, Any] | None:
    tokens = title_tokens(str(item.get("title", "")))
    if not tokens or not transcript:
        return None
    best: dict[str, Any] | None = None
    denom = max(1, min(7, len(tokens)))
    for index, row in enumerate(transcript):
        seconds = float(row["seconds"])
        if seconds < earliest:
            continue
        context = transcript_context(transcript, index)
        context_tokens = content_token_set(context)
        row_text = str(row["text"])
        row_tokens = content_token_set(row_text)
        matched = [token for token in tokens if token in context_tokens]
        match_score = min(len(matched), denom) / denom
        has_transition = bool(TRANSITION_RE.search(context))
        score = match_score + (0.25 if has_transition else 0.0)
        if TRANSITION_RE.search(row_text):
            score += 0.08
        if any(token in row_tokens for token in tokens):
            score += 0.05
        if len(matched) >= 2 and tokens[0] in matched:
            score += 0.05
        if score < 0.42 or (not has_transition and score < 0.68):
            continue
        if best is None or score > best["score"]:
            best = {
                "seconds": seconds,
                "score": round(score, 3),
                "matched_title_tokens": matched[:10],
                "cue": context[:240],
            }
    return best


def align_schedule_to_transcript(schedule: list[dict[str, Any]], transcript: list[dict[str, Any]], final_end: float) -> list[dict[str, Any]]:
    if not schedule:
        return schedule
    aligned: list[dict[str, Any]] = []
    earliest = 0.0
    for item in schedule:
        rough_start = parse_time_seconds(str(item.get("schedule_start", "00:00:00.000"))) if item.get("schedule_start") else earliest
        match = find_title_alignment(item, transcript, max(0.0, earliest - 15.0))
        if match:
            start = float(match["seconds"])
            confidence = 0.82 if match["score"] < 0.75 else 0.9
            evidence = ["schedule", "transcript_title_alignment"]
            alignment = match
        else:
            start = max(rough_start, earliest)
            confidence = 0.68
            evidence = ["schedule", "rough_clock_alignment"]
            alignment = None
        aligned.append({**item, "_aligned_start_seconds": start, "_confidence": confidence, "_evidence": evidence, "_alignment": alignment})
        earliest = start + 120.0

    for idx, item in enumerate(aligned):
        start = float(item["_aligned_start_seconds"])
        if idx + 1 < len(aligned):
            end = float(aligned[idx + 1]["_aligned_start_seconds"])
        elif item.get("schedule_end"):
            end = max(parse_time_seconds(str(item["schedule_end"])), start + 1.0)
            end = max(end, final_end)
        else:
            end = final_end
        item["_aligned_end_seconds"] = max(start + 1.0, end)
    return aligned


def template_segments(out_dir: Path, first_content: float, final_end: float) -> Path:
    target = ensure_dir(out_dir / "segmentation") / "manual_segments.template.yaml"
    target.write_text(
        "talks:\n"
        "  - title: Replace with talk title\n"
        "    type: oral\n"
        "    speakers: []\n"
        f"    schedule_start: {format_time(first_content)}\n"
        f"    schedule_end: {format_time(final_end)}\n",
        encoding="utf-8",
    )
    return target


def aligned_talks(out_dir: Path, cfg: dict[str, Any], *, manual_segments: Path | None = None) -> list[dict[str, Any]]:
    transcript = timeline_lines(out_dir / "asr" / "timeline.txt")
    intervals = read_json(out_dir / "slide_intervals.json") if (out_dir / "slide_intervals.json").exists() else []
    first_content = transcript[0]["seconds"] if transcript else (intervals[0]["start_seconds"] if intervals else 0.0)
    final_end = max([row["seconds"] for row in transcript] + [i["end_seconds"] for i in intervals] + [first_content + 5])

    if manual_segments:
        schedule = load_manual_segments(manual_segments)
    else:
        schedule = parse_schedule_html(out_dir / "raw" / "page.html")
    if not schedule:
        template = template_segments(out_dir, first_content, final_end)
        schedule = [{"title": "Full Replay", "type": "talk", "speakers": [], "schedule_start": format_time(first_content), "schedule_end": format_time(final_end), "template": str(template.resolve())}]
    else:
        schedule = normalize_schedule(schedule, first_content, final_end)
        schedule = align_schedule_to_transcript(schedule, transcript, final_end)

    talks: list[dict[str, Any]] = []
    for index, item in enumerate(schedule, start=1):
        start = float(item.get("_aligned_start_seconds", parse_time_seconds(str(item.get("schedule_start", format_time(first_content)))) if ":" in str(item.get("schedule_start", "")) else first_content))
        end = float(item.get("_aligned_end_seconds", parse_time_seconds(str(item.get("schedule_end", format_time(final_end)))) if ":" in str(item.get("schedule_end", "")) else final_end))
        title = str(item.get("title") or f"Talk {index}")
        event_type = str(item.get("type") or "talk")
        reportable = is_reportable(title, event_type) and (end - start) >= float(cfg["segmentation"].get("min_talk_seconds", 120))
        evidence = item.get("_evidence", ["schedule" if not item.get("template") else "manual_template_required", "asr/slide bounds"])
        rough_start = str(item.get("schedule_start", format_time(start)))
        rough_end = str(item.get("schedule_end", format_time(end)))
        talk = {
            "talk_id": f"talk-{index:03d}",
            "title": title,
            "type": event_type,
            "speakers": item.get("speakers", []),
            "schedule_start": rough_start,
            "schedule_end": rough_end,
            "aligned_start": format_time(start),
            "aligned_end": format_time(end),
            "confidence": item.get("_confidence", 0.55 if item.get("template") else 0.75),
            "reportable": reportable,
            "evidence": evidence,
        }
        if item.get("href"):
            talk["source_url"] = item["href"]
        if item.get("abstract"):
            talk["abstract"] = item["abstract"]
        if item.get("_alignment"):
            talk["alignment"] = item["_alignment"]
        talks.append(talk)
    return talks


def clipped_occurrences(occurrences: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    clipped: list[dict[str, Any]] = []
    for item in occurrences:
        raw_start = parse_time_seconds(item["start_time"])
        raw_end = parse_time_seconds(item["end_time"])
        overlap_start = max(start, raw_start)
        overlap_end = min(end, raw_end)
        overlap = overlap_end - overlap_start
        if overlap <= 0:
            continue
        duration = max(0.001, raw_end - raw_start)
        boundary_sliver = (raw_start < start or raw_end > end) and overlap < min(5.0, max(1.0, duration * 0.05))
        if boundary_sliver:
            continue
        clipped.append({
            **item,
            "start_time": format_time(overlap_start),
            "end_time": format_time(overlap_end),
            "duration_seconds": round(overlap, 3),
            "original_start_time": item["start_time"],
            "original_end_time": item["end_time"],
        })
    return clipped


def grouped_intervals_for_talk(out_dir: Path, start: float, end: float) -> list[dict[str, Any]]:
    groups_path = out_dir / "dedup_groups.json"
    if not groups_path.exists():
        intervals = read_json(out_dir / "slide_intervals.json")
        return [
            item for item in intervals
            if clipped_occurrences([{"start_time": item["start_time"], "end_time": item["end_time"], "duration_seconds": item.get("duration_seconds", 0), "source_times": item.get("source_times", [])}], start, end)
        ]

    talk_groups: list[dict[str, Any]] = []
    for group in read_json(groups_path):
        occurrences = clipped_occurrences(group.get("all_intervals", []), start, end)
        if not occurrences:
            continue
        main = max(occurrences, key=lambda item: item.get("duration_seconds", 0))
        talk_groups.append({
            "cluster_id": group["cluster_id"],
            "representative_time": group["representative_time"],
            "representative_path": group["representative_path"],
            "all_source_times": group.get("all_source_times", []),
            "duplicate_times": group.get("duplicate_times", []),
            "all_intervals": occurrences,
            "main_interval": main,
            "start_time": main["start_time"],
            "end_time": main["end_time"],
            "duration_seconds": main["duration_seconds"],
        })
    return sorted(talk_groups, key=lambda item: parse_time_seconds(item["all_intervals"][0]["start_time"]))


def write_review(out_dir: Path, talks: list[dict[str, Any]]) -> None:
    seg_dir = ensure_dir(out_dir / "segmentation")
    rows = [
        "<!doctype html><meta charset='utf-8'><title>Segmentation Review</title>",
        "<style>body{font-family:system-ui,sans-serif;margin:24px} table{border-collapse:collapse;width:100%} td,th{border:1px solid #ddd;padding:6px}</style>",
        "<h1>Segmentation Review</h1><table><tr><th>ID</th><th>Title</th><th>Type</th><th>Aligned</th><th>Report</th><th>Confidence</th></tr>",
    ]
    for talk in talks:
        rows.append(f"<tr><td>{talk['talk_id']}</td><td>{talk['title']}</td><td>{talk['type']}</td><td>{talk['aligned_start']} - {talk['aligned_end']}</td><td>{talk['reportable']}</td><td>{talk['confidence']}</td></tr>")
    rows.append("</table>")
    (seg_dir / "review.html").write_text("\n".join(rows), encoding="utf-8")


def package_talks(out_dir: Path, talks: list[dict[str, Any]]) -> None:
    transcript_path = out_dir / "asr" / "timeline.txt"
    talks_root = ensure_dir(out_dir / "talks")
    for talk in talks:
        if not talk.get("reportable"):
            continue
        start = parse_time_seconds(talk["aligned_start"])
        end = parse_time_seconds(talk["aligned_end"])
        slug = slugify(f"{talk['talk_id']}_{talk['title']}", fallback=talk["talk_id"])
        talk["slug"] = slug
        talk_dir = ensure_dir(talks_root / slug)
        slides_dir = ensure_dir(talk_dir / "slides")
        talk_intervals = grouped_intervals_for_talk(out_dir, start, end)
        for interval in talk_intervals:
            src = Path(interval["representative_path"])
            if src.exists():
                shutil.copy2(src, slides_dir / src.name)
                interval["talk_slide_path"] = str((slides_dir / src.name).resolve())
        rows = subset_timeline(transcript_path, start, end)
        write_timeline(talk_dir / "timeline.txt", rows)
        write_json(talk_dir / "slide_intervals.json", talk_intervals)
        write_json(talk_dir / "metadata.json", talk)
        (talk_dir / "report_prompt.md").write_text(
            f"# Report Prompt\n\n请基于本文件夹中的 slides、slide_intervals.json、timeline.txt 为 `{talk['title']}` 写中文图文研究报告。"
            "\n不要使用未在 PPT 或 transcript 中出现的信息；英文术语保持英文。\n",
            encoding="utf-8",
        )


def segment(out_dir: Path, cfg: dict[str, Any], *, manual_segments: Path | None = None) -> list[dict[str, Any]]:
    talks = aligned_talks(out_dir, cfg, manual_segments=manual_segments)
    seg_dir = ensure_dir(out_dir / "segmentation")
    package_talks(out_dir, talks)
    write_json(seg_dir / "talks.json", talks)
    with (seg_dir / "talks.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["talk_id", "slug", "title", "type", "schedule_start", "schedule_end", "aligned_start", "aligned_end", "confidence", "reportable"])
        writer.writeheader()
        writer.writerows([{key: talk.get(key) for key in writer.fieldnames} for talk in talks])
    write_review(out_dir, talks)
    write_json(out_dir / "segmentation_manifest.json", {"talk_count": len(talks), "reportable_count": sum(1 for talk in talks if talk.get("reportable"))})
    return talks
