from __future__ import annotations

import json
import re
import urllib.request
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .auth import get_openai_api_key, openai_client_kwargs
from .ingest import download_audio
from .utils import ensure_dir, format_time, read_json, require_tool, run, write_json


def strip_vtt_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_vtt_time(value: str) -> float:
    value = value.split()[0].replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        hours, minutes, seconds = "0", parts[0], parts[1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def vtt_to_rows(vtt_path: Path) -> list[dict[str, Any]]:
    lines = vtt_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    rows: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" not in line:
            i += 1
            continue
        start_raw, end_raw = [part.strip() for part in line.split("-->", 1)]
        start = parse_vtt_time(start_raw)
        end = parse_vtt_time(end_raw)
        i += 1
        text_lines: list[str] = []
        while i < len(lines) and lines[i].strip():
            text = strip_vtt_text(lines[i])
            if text:
                text_lines.append(text)
            i += 1
        text = strip_vtt_text(" ".join(text_lines))
        if text:
            rows.append({"start": start, "end": end, "time": format_time(start), "text": text, "source": "subtitle", "confidence": None})
    return rows


def write_asr_outputs(rows: list[dict[str, Any]], asr_dir: Path) -> dict[str, str]:
    ensure_dir(asr_dir)
    timeline = asr_dir / "timeline.txt"
    jsonl = asr_dir / "timeline.jsonl"
    timeline.write_text("".join(f"[{row['time']}] {row['text']}\n" for row in rows), encoding="utf-8")
    jsonl.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {"timeline": str(timeline.resolve()), "jsonl": str(jsonl.resolve())}


def subtitle_from_info(info_json: Path, raw_dir: Path) -> Path | None:
    stem = info_json.stem.replace(".info", "")
    local = sorted(info_json.parent.glob(f"{stem}*.vtt"))
    if local:
        return local[0]
    data = read_json(info_json)
    entries = (data.get("subtitles") or {}).get("en") or []
    if not entries:
        return None
    url = entries[0].get("url")
    if not url:
        return None
    target = ensure_dir(raw_dir / "subtitles") / f"{stem}.en.vtt"
    urllib.request.urlretrieve(url, target)
    return target


def extract_wav(media_path: Path, asr_dir: Path) -> Path:
    ffmpeg = require_tool("ffmpeg")
    wav = ensure_dir(asr_dir / "audio") / f"{media_path.stem}.wav"
    if wav.exists() and wav.stat().st_size > 0:
        return wav
    run([ffmpeg, "-y", "-i", str(media_path), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    return wav


def transcribe_faster_whisper(audio_path: Path, model_size: str) -> list[dict[str, Any]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit("Install faster-whisper or choose OpenAI transcription fallback.") from exc
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, _info = model.transcribe(str(audio_path), vad_filter=True)
    rows = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            rows.append({"start": seg.start, "end": seg.end, "time": format_time(seg.start), "text": text, "source": "faster-whisper", "confidence": None})
    return rows


def faster_whisper_available() -> bool:
    return find_spec("faster_whisper") is not None


def transcribe_openai(audio_path: Path, model: str = "gpt-4o-transcribe") -> list[dict[str, Any]]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("Install openai to use OpenAI transcription fallback.") from exc
    client = OpenAI(**openai_client_kwargs())
    with audio_path.open("rb") as f:
        transcript = client.audio.transcriptions.create(model=model, file=f, response_format="verbose_json")
    rows = []
    for segment in getattr(transcript, "segments", []) or []:
        start = float(segment["start"] if isinstance(segment, dict) else segment.start)
        end = float(segment["end"] if isinstance(segment, dict) else segment.end)
        text = segment["text"] if isinstance(segment, dict) else segment.text
        rows.append({"start": start, "end": end, "time": format_time(start), "text": text.strip(), "source": "openai-transcription", "confidence": None})
    if not rows and getattr(transcript, "text", None):
        rows.append({"start": 0.0, "end": 0.0, "time": "00:00:00.000", "text": transcript.text.strip(), "source": "openai-transcription", "confidence": None})
    return rows


def preserve_audio_artifact(source: str, out_dir: Path, asr_dir: Path, ingest_manifest: dict[str, Any], *, cookies_from_browser: str | None = None) -> dict[str, str]:
    media_items = ingest_manifest.get("media") or []
    media_path = Path(media_items[0]) if media_items else download_audio(source, out_dir, cookies_from_browser=cookies_from_browser)
    wav_path = extract_wav(media_path, asr_dir)
    return {"media": str(media_path.resolve()), "wav": str(wav_path.resolve())}


def run_asr(source: str, out_dir: Path, cfg: dict[str, Any], *, cookies_from_browser: str | None = None) -> dict[str, str]:
    raw_dir = out_dir / "raw"
    ingest_manifest = read_json(raw_dir / "ingest_manifest.json")
    asr_dir = out_dir / "asr"
    asr_cfg = cfg.get("asr", {})
    rows: list[dict[str, Any]] = []
    audio_outputs: dict[str, str] = {}
    audio_warning: str | None = None

    if asr_cfg.get("preferred") == "subtitles":
        for info in ingest_manifest.get("info_json", []):
            vtt = subtitle_from_info(Path(info), raw_dir)
            if vtt:
                rows = vtt_to_rows(vtt)
                break

    if rows and asr_cfg.get("save_audio", False):
        try:
            audio_outputs = preserve_audio_artifact(source, out_dir, asr_dir, ingest_manifest, cookies_from_browser=cookies_from_browser)
        except SystemExit as exc:
            audio_warning = str(exc)
            if asr_cfg.get("audio_required", False):
                raise
            print(f"Warning: could not preserve audio artifact: {exc}")

    if not rows:
        media_items = ingest_manifest.get("media") or []
        media_path = Path(media_items[0]) if media_items else download_audio(source, out_dir, cookies_from_browser=cookies_from_browser)
        audio_path = extract_wav(media_path, asr_dir)
        audio_outputs = {"media": str(media_path.resolve()), "wav": str(audio_path.resolve())}
        fallback = asr_cfg.get("fallback", "faster_whisper_or_openai")
        if fallback == "openai":
            rows = transcribe_openai(audio_path)
        elif fallback in {"faster_whisper_or_openai", "auto"}:
            if faster_whisper_available():
                rows = transcribe_faster_whisper(audio_path, asr_cfg.get("whisper_model_size", "medium"))
            elif get_openai_api_key():
                rows = transcribe_openai(audio_path)
            else:
                raise SystemExit("Install faster-whisper or configure an OpenAI API key for ASR fallback.")
        else:
            rows = transcribe_faster_whisper(audio_path, asr_cfg.get("whisper_model_size", "medium"))

    outputs = write_asr_outputs(rows, asr_dir)
    manifest = {"segments": len(rows), **outputs, "audio": audio_outputs}
    if audio_warning:
        manifest["audio_warning"] = audio_warning
    write_json(asr_dir / "asr_manifest.json", manifest)
    return outputs
