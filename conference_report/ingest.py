from __future__ import annotations

import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .utils import ensure_dir, require_tool, run, slugify, write_json


MEDIA_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".m4a", ".mp3", ".opus", ".wav", ".aac"}
SENSITIVE_QUERY_KEYS = (
    "player_token",
    "token",
    "access_token",
    "session_token",
    "analytics_session_token",
    "api_key",
    "apikey",
    "key",
    "signature",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-policy",
    "policy",
    "key-pair-id",
)
SENSITIVE_ATTRS = (
    "data-token",
    "data-player-token",
    "data-analytics-session-token",
    "data-analytics-user-uuid",
    "data-analytics-session-uuid",
    "data-api-key",
    "data-uid",
    "data-user-id",
    "data-session-token",
)
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{12,}\b")


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


def redact_sensitive_text(text: str) -> str:
    query_pattern = re.compile(
        r"((?:[?&]|&amp;|\\u0026)(" + "|".join(re.escape(key) for key in SENSITIVE_QUERY_KEYS) + r")=)([^&\"'<>\s\\]+)",
        flags=re.IGNORECASE,
    )
    attr_pattern = re.compile(
        r"(\b(?:" + "|".join(re.escape(attr) for attr in SENSITIVE_ATTRS) + r")\s*=\s*['\"])([^'\"]+)(['\"])",
        flags=re.IGNORECASE,
    )
    text = attr_pattern.sub(r"\1REDACTED\3", text)
    text = query_pattern.sub(r"\1REDACTED", text)
    text = JWT_RE.sub("REDACTED_JWT", text)
    text = AWS_ACCESS_KEY_RE.sub("REDACTED_AWS_ACCESS_KEY", text)
    return text


def redact_text_file(path: Path) -> bool:
    try:
        original = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    redacted = redact_sensitive_text(original)
    if redacted == original:
        return False
    path.write_text(redacted, encoding="utf-8")
    return True


def redact_html_artifacts(raw_dir: Path, dump_dir: Path) -> int:
    candidates = [raw_dir / "page.html"]
    if dump_dir.exists():
        candidates.extend(sorted(path for path in dump_dir.glob("*.dump") if path.is_file()))
    redacted = 0
    for path in candidates:
        if path.exists() and redact_text_file(path):
            redacted += 1
    return redacted


def sanitize_page_dump_filenames(dump_dir: Path) -> int:
    if not dump_dir.exists():
        return 0
    dumps = sorted(path for path in dump_dir.glob("*.dump") if path.is_file())
    if not dumps:
        return 0
    width = max(4, len(str(len(dumps))))
    renamed = 0
    for index, path in enumerate(dumps, start=1):
        target = dump_dir / f"page-{index:0{width}d}.dump"
        if path == target:
            continue
        if target.exists():
            target = dump_dir / f"page-{index:0{width}d}-{abs(hash(path.name)) & 0xffff:x}.dump"
        path.rename(target)
        renamed += 1
    return renamed


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

    yt_dlp = require_tool("yt-dlp")
    save_public_page(source, raw_dir)
    output_template = str(info_dir / "%(playlist_index|000)s-%(title).160B.%(ext)s")
    cmd = [
        yt_dlp,
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
    sanitized_dumps = sanitize_page_dump_filenames(page_dump_dir)
    redacted_files = redact_html_artifacts(raw_dir, page_dump_dir)
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
        manifest["page_dump_files_sanitized"] = sanitized_dumps
        manifest["html_files_redacted"] = redacted_files
    write_json(raw_dir / "ingest_manifest.json", manifest)
    return manifest


def download_audio(source: str, out_dir: Path, *, cookies_from_browser: str | None = None, download_format: str = "ba/bestaudio/b") -> Path:
    yt_dlp = require_tool("yt-dlp")
    audio_dir = ensure_dir(out_dir / "raw" / "audio")
    output_template = str(audio_dir / "%(playlist_index|000)s-%(title).160B.%(ext)s")
    cmd = [
        yt_dlp,
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
