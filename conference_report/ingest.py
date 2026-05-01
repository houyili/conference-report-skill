from __future__ import annotations

import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .utils import ensure_dir, require_tool, run, slugify, write_json


MEDIA_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".m4a", ".mp3", ".opus", ".wav", ".aac"}


def save_public_page(url: str, raw_dir: Path) -> Path | None:
    if not url.startswith(("http://", "https://")):
        return None
    target = raw_dir / "page.html"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            target.write_bytes(response.read())
        return target
    except Exception as exc:
        print(f"Warning: could not save page HTML: {exc}")
        return None


def promote_best_page_dump(source: str, raw_dir: Path, dump_dir: Path) -> Path | None:
    if not source.startswith(("http://", "https://")) or not dump_dir.exists():
        return None
    host = urlparse(source).netloc.lower()
    candidates: list[tuple[int, int, Path]] = []
    for path in dump_dir.glob("*.dump"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lowered = text[:200_000].lower()
        if "<html" not in lowered and "<!doctype" not in lowered:
            continue
        score = 0
        if host and host in path.name.lower():
            score += 30
        if "track-schedule-card" in lowered:
            score += 80
        if "schedule-row" in lowered or "schedule-html-detail" in lowered:
            score += 30
        if re.search(r"/virtual/\d{4}/(?:oral|poster|submission|workshop)/", lowered):
            score += 25
        if "logged in" in lowered and "to view this content" in lowered:
            score -= 60
        candidates.append((score, path.stat().st_size, path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    score, _, best = candidates[0]
    if score <= 0:
        return None
    target = raw_dir / "page.html"
    shutil.copy2(best, target)
    return target


def ingest(source: str, out_dir: Path, *, cookies_from_browser: str | None = None, playlist_items: str = "1") -> dict[str, Any]:
    raw_dir = ensure_dir(out_dir / "raw")
    info_dir = ensure_dir(raw_dir / "info")
    page_dump_dir = ensure_dir(raw_dir / "page_dump")
    manifest: dict[str, Any] = {"source": source, "mode": "metadata", "info_json": [], "subtitles": [], "media": []}

    source_path = Path(source).expanduser()
    if source_path.exists():
        media_dir = ensure_dir(raw_dir / "media")
        copied = media_dir / source_path.name
        if source_path.resolve() != copied.resolve():
            shutil.copy2(source_path, copied)
        manifest["mode"] = "local_file"
        manifest["media"].append(str(copied.resolve()))
        write_json(raw_dir / "ingest_manifest.json", manifest)
        return manifest

    require_tool("yt-dlp")
    save_public_page(source, raw_dir)
    output_template = str(info_dir / "%(playlist_index|000)s-%(title).160B.%(ext)s")
    cmd = [
        "yt-dlp",
        "--yes-playlist",
        "--playlist-items",
        playlist_items,
        "--skip-download",
        "--write-info-json",
        "--write-subs",
        "--sub-langs",
        "en",
        "--sub-format",
        "vtt",
        "-o",
        output_template,
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    if source.startswith(("http://", "https://")):
        cmd.append("--write-pages")
    cmd.append(source)
    proc = run(cmd, check=False, cwd=page_dump_dir)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit("yt-dlp metadata ingest failed.")

    promoted = promote_best_page_dump(source, raw_dir, page_dump_dir)
    info_files = sorted(info_dir.glob("*.info.json"))
    if not info_files:
        raise SystemExit("No metadata was extracted. The page may require login/registration cookies.")
    manifest["info_json"] = [str(path.resolve()) for path in info_files if not path.name.startswith("0-")]
    manifest["subtitles"] = [str(path.resolve()) for path in sorted(info_dir.glob("*.vtt"))]
    if not manifest["info_json"]:
        manifest["info_json"] = [str(path.resolve()) for path in info_files]
    manifest["run_name"] = slugify(Path(manifest["info_json"][0]).stem.replace(".info", ""), fallback="conference")
    if promoted:
        manifest["page_html"] = str(promoted.resolve())
        manifest["page_dump_dir"] = str(page_dump_dir.resolve())
    write_json(raw_dir / "ingest_manifest.json", manifest)
    return manifest


def download_audio(source: str, out_dir: Path, *, cookies_from_browser: str | None = None, download_format: str = "ba/bestaudio/b") -> Path:
    require_tool("yt-dlp")
    audio_dir = ensure_dir(out_dir / "raw" / "audio")
    output_template = str(audio_dir / "%(playlist_index|000)s-%(title).160B.%(ext)s")
    cmd = [
        "yt-dlp",
        "--yes-playlist",
        "--playlist-items",
        "1",
        "--ignore-errors",
        "--restrict-filenames",
        "-f",
        download_format,
        "-o",
        output_template,
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    cmd.append(source)
    proc = run(cmd, check=False)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit("Audio download failed.")
    media = sorted(path for path in audio_dir.iterdir() if path.suffix.lower() in MEDIA_EXTS)
    if not media:
        raise SystemExit("No audio/media file was downloaded.")
    return media[0]
