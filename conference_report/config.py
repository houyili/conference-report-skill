from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "api": {
        "provider": "openai_responses",
        "model": "gpt-5.1",
        "max_parallel_reports": 4,
        "dry_run_without_key": True,
    },
    "asr": {
        "preferred": "subtitles",
        "fallback": "faster_whisper_or_openai",
        "whisper_model_size": "medium",
        "save_audio": True,
        "audio_required": False,
    },
    "segmentation": {
        "source": "schedule_with_alignment",
        "generate_review": True,
        "min_talk_seconds": 120,
    },
    "slides": {
        "video_mode": "scene",
        "interval_seconds": 10.0,
        "scene_threshold": 0.08,
    },
    "dedupe": {
        "mode": "conservative",
        "lookback_kept": 8,
        "mean_threshold": 1.2,
        "changed_threshold": 0.006,
        "hash_threshold": 6,
        "agent_merge_confidence_threshold": 0.75,
    },
    "embeddings": {
        "enabled": True,
        "provider": "local_siglip",
        "model": "google/siglip-base-patch16-224",
        "device": "auto",
        "cache_dir": "embeddings",
        "similarity_threshold": 0.92,
        "candidate_limit": 200,
    },
    "report": {
        "writer": "auto",
        "language": "zh",
        "preserve_terms": "en",
        "detail": "slide_by_slide",
        "max_overview_slides": 12,
        "max_transcript_chars_per_slide": 2500,
    },
}

CONFIG_PROFILE_OVERRIDES: dict[str, dict[str, Any]] = {
    "full": {},
    "fast": {
        "asr": {
            "save_audio": False,
            "audio_required": False,
        },
    },
}

CONFIG_PROFILES = tuple(CONFIG_PROFILE_OVERRIDES.keys())


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def default_config_for_profile(profile: str = "full") -> dict[str, Any]:
    if profile not in CONFIG_PROFILE_OVERRIDES:
        choices = ", ".join(CONFIG_PROFILES)
        raise SystemExit(f"Unsupported config profile: {profile}. Choose one of: {choices}")
    return deep_merge(DEFAULT_CONFIG, CONFIG_PROFILE_OVERRIDES[profile])


def load_config(path: Path | None, *, profile: str = "full") -> dict[str, Any]:
    cfg = default_config_for_profile(profile)
    if path is None:
        return cfg
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text) or {}
    return deep_merge(cfg, data)


def write_default_config(path: Path, *, profile: str = "full") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = default_config_for_profile(profile)
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
