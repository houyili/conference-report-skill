from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import Any

from .utils import ensure_dir, format_time, read_json, require_tool, run, write_json


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


def slide_id_from_chapter(title: str) -> str | None:
    match = re.search(r"Slide\s+(\d+)", title, re.IGNORECASE)
    return f"{int(match.group(1)):03d}" if match else None


def download_url(url: str, target: Path, referer: str | None = None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer or "https://slideslive.com/"})
    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())


def slides_from_metadata(info_json: Path, slides_dir: Path) -> int:
    data = read_json(info_json)
    chapters = data.get("chapters") or []
    thumbnails = data.get("thumbnails") or []
    thumb_by_id = {str(item.get("id")): item.get("url") for item in thumbnails if item.get("id") and item.get("url")}
    if not chapters or not thumb_by_id:
        return 0
    ensure_dir(slides_dir)
    count = 0
    for chapter in chapters:
        slide_id = slide_id_from_chapter(str(chapter.get("title") or ""))
        if not slide_id or slide_id not in thumb_by_id:
            continue
        target = slides_dir / f"[{format_time(float(chapter.get('start_time') or 0))}].png"
        if target.exists():
            continue
        try:
            download_url(thumb_by_id[slide_id], target, data.get("webpage_url"))
            count += 1
        except Exception as exc:
            print(f"Warning: slide download failed for {slide_id}: {exc}")
    return count


def slides_from_video(media_path: Path, slides_dir: Path, *, mode: str = "scene", interval_seconds: float = 10.0, scene_threshold: float = 0.08) -> int:
    require_tool("ffmpeg")
    ensure_dir(slides_dir)
    if mode == "interval":
        pattern = slides_dir / "raw_%06d.png"
        run(["ffmpeg", "-y", "-i", str(media_path), "-vf", f"fps=1/{interval_seconds}", str(pattern)])
        count = 0
        for idx, frame in enumerate(sorted(slides_dir.glob("raw_*.png"))):
            frame.rename(slides_dir / f"[{format_time(idx * interval_seconds)}].png")
            count += 1
        return count

    first = slides_dir / "[00:00:00.000].png"
    run(["ffmpeg", "-y", "-ss", "0", "-i", str(media_path), "-frames:v", "1", str(first)])
    scene_log = slides_dir / "scene.log"
    raw_pattern = slides_dir / "raw_%06d.png"
    vf = f"select='gt(scene,{scene_threshold})',metadata=print:file={scene_log}"
    run(["ffmpeg", "-y", "-i", str(media_path), "-vf", vf, "-vsync", "vfr", str(raw_pattern)])
    times: list[float] = []
    for line in scene_log.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.search(r"pts_time:([0-9.]+)", line)
        if match:
            times.append(float(match.group(1)))
    count = 1
    for frame, seconds in zip(sorted(slides_dir.glob("raw_*.png")), times):
        frame.rename(slides_dir / f"[{format_time(seconds)}].png")
        count += 1
    return count


def extract_slides(out_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    raw_manifest = read_json(out_dir / "raw" / "ingest_manifest.json")
    slides_dir = ensure_dir(out_dir / "slides_original")
    count = 0
    source = "metadata"
    for info in raw_manifest.get("info_json", []):
        count += slides_from_metadata(Path(info), slides_dir)
    if count == 0 and raw_manifest.get("media"):
        media = Path(raw_manifest["media"][0])
        if media.suffix.lower() in VIDEO_EXTS:
            source = "video"
            count = slides_from_video(media, slides_dir)
    manifest = {"slides_dir": str(slides_dir.resolve()), "count": len(list(slides_dir.glob("*.png"))), "source": source}
    write_json(out_dir / "slides_manifest.json", manifest)
    return manifest
