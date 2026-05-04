from __future__ import annotations

import math
import re
import struct
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .utils import ensure_dir, extract_time_from_name, read_json, write_json


EmbedImage = Callable[[Path], list[float]]


def safe_time_id(path: Path) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "-", extract_time_from_name(path)).strip("-") or path.stem


def embedding_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return dict(cfg.get("embeddings", {}) or {})


def embedding_slides_dir(out_dir: Path, cfg: dict[str, Any]) -> Path:
    cache_root = str(embedding_config(cfg).get("cache_dir", "embeddings"))
    return out_dir / cache_root / "slides"


def write_npy_vector(path: Path, vector: list[float]) -> None:
    ensure_dir(path.parent)
    header = {
        "descr": "<f4",
        "fortran_order": False,
        "shape": (len(vector),),
    }
    header_text = repr(header)
    header_text = header_text.replace('"', "'")
    header_bytes = header_text.encode("latin1")
    preamble_len = 6 + 2 + 2
    padding = 16 - ((preamble_len + len(header_bytes) + 1) % 16)
    if padding == 16:
        padding = 0
    header_bytes = header_bytes + b" " * padding + b"\n"
    data = struct.pack(f"<{len(vector)}f", *[float(value) for value in vector])
    path.write_bytes(b"\x93NUMPY" + bytes([1, 0]) + struct.pack("<H", len(header_bytes)) + header_bytes + data)


def read_npy_vector(path: Path) -> list[float]:
    data = path.read_bytes()
    if not data.startswith(b"\x93NUMPY"):
        raise ValueError(f"Not a .npy file: {path}")
    major = data[6]
    if major != 1:
        raise ValueError(f"Unsupported .npy version in {path}")
    header_len = struct.unpack("<H", data[8:10])[0]
    body = data[10 + header_len :]
    if len(body) % 4 != 0:
        raise ValueError(f"Invalid float32 vector payload in {path}")
    count = len(body) // 4
    return [round(float(value), 8) for value in struct.unpack(f"<{count}f", body)]


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [float(value) / norm for value in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    a_norm = l2_normalize(a)
    b_norm = l2_normalize(b)
    return sum(left * right for left, right in zip(a_norm, b_norm))


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch
    except ImportError:
        return "cpu"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_local_siglip_embedder(cfg: dict[str, Any]) -> EmbedImage:
    emb_cfg = embedding_config(cfg)
    model_name = str(emb_cfg.get("model", "google/siglip-base-patch16-224"))
    device = resolve_device(str(emb_cfg.get("device", "auto")))
    try:
        import torch
        from transformers import AutoModel, AutoProcessor
    except ImportError as exc:
        raise ImportError(
            "Local semantic embeddings require the optional embeddings extra. "
            'Install with `pip install -e ".[embeddings]"` or disable embeddings.enabled.'
        ) from exc

    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(device)
    model.eval()

    def embed(path: Path) -> list[float]:
        with Image.open(path) as image:
            inputs = processor(images=image.convert("RGB"), return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.no_grad():
            if hasattr(model, "get_image_features"):
                features = model.get_image_features(**inputs)
            else:
                outputs = model(**inputs)
                features = getattr(outputs, "image_embeds", None)
                if features is None:
                    features = getattr(outputs, "pooler_output", None)
                if features is None:
                    raise RuntimeError(f"Model {model_name} did not return image embeddings")
        return [float(value) for value in features[0].detach().cpu().float().tolist()]

    return embed


def compute_slide_embedding_cache(
    slide_paths: list[Path],
    out_dir: Path,
    cfg: dict[str, Any],
    *,
    embed_image: EmbedImage | None = None,
) -> list[dict[str, Any]]:
    emb_cfg = embedding_config(cfg)
    provider = str(emb_cfg.get("provider", "local_siglip"))
    if embed_image is None:
        if provider != "local_siglip":
            raise ValueError(f"Unsupported embeddings provider: {provider}")
        embed_image = load_local_siglip_embedder(cfg)
    cache_dir = ensure_dir(embedding_slides_dir(out_dir, cfg))
    model = str(emb_cfg.get("model", "google/siglip-base-patch16-224"))
    rows: list[dict[str, Any]] = []
    for slide in slide_paths:
        slide = slide.resolve()
        time = extract_time_from_name(slide)
        cache_id = safe_time_id(slide)
        meta_path = cache_dir / f"{cache_id}.json"
        vector_path = cache_dir / f"{cache_id}.npy"
        cache_hit = meta_path.exists() and vector_path.exists()
        if cache_hit:
            vector = read_npy_vector(vector_path)
        else:
            vector = l2_normalize([float(value) for value in embed_image(slide)])
            write_npy_vector(vector_path, vector)
            write_json(
                meta_path,
                {
                    "slide_path": str(slide),
                    "time": time,
                    "provider": provider,
                    "model": model,
                    "vector_path": str(vector_path.resolve()),
                    "dimensions": len(vector),
                },
            )
        rows.append(
            {
                "slide_path": str(slide),
                "time": time,
                "provider": provider,
                "model": model,
                "vector_path": str(vector_path.resolve()),
                "metadata_path": str(meta_path.resolve()),
                "dimensions": len(vector),
                "vector": vector,
                "cache_hit": cache_hit,
            }
        )
    write_json(
        out_dir / str(emb_cfg.get("cache_dir", "embeddings")) / "embedding_manifest.json",
        {
            "enabled": True,
            "provider": provider,
            "model": model,
            "slide_count": len(rows),
            "cache_hits": sum(1 for row in rows if row["cache_hit"]),
            "cache_dir": str(cache_dir.resolve()),
        },
    )
    return rows


def semantic_candidates_from_embeddings(
    rows: list[dict[str, Any]],
    *,
    threshold: float = 0.92,
    max_candidates: int | None = None,
    excluded_pairs: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    excluded_pairs = excluded_pairs or set()
    candidates: list[dict[str, Any]] = []
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1 :]:
            pair = tuple(sorted([str(left["time"]), str(right["time"])]))
            if pair in excluded_pairs:
                continue
            similarity = cosine_similarity([float(value) for value in left["vector"]], [float(value) for value in right["vector"]])
            if similarity < threshold:
                continue
            candidates.append(
                {
                    "candidate_id": f"semantic:{len(candidates) + 1:04d}",
                    "slide_a_time": left["time"],
                    "slide_b_time": right["time"],
                    "slide_a_path": left["slide_path"],
                    "slide_b_path": right["slide_path"],
                    "similarity": round(similarity, 6),
                    "decision": "needs_agent_review",
                }
            )
    candidates.sort(key=lambda item: item["similarity"], reverse=True)
    if max_candidates is not None:
        candidates = candidates[:max_candidates]
    for idx, item in enumerate(candidates, start=1):
        item["candidate_id"] = f"semantic:{idx:04d}"
    return candidates


def semantic_review_tasks(out_dir: Path, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    review_dir = ensure_dir(out_dir / "dedupe" / "agent_reviews")
    tasks: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates, start=1):
        task_id = f"dedupe-semantic-review:{idx:04d}"
        output_path = (review_dir / f"{idx:04d}.json").resolve()
        tasks.append(
            {
                "task_id": task_id,
                "stage": "dedupe_semantic_review",
                "candidate_id": candidate["candidate_id"],
                "input_paths": [
                    str(Path(candidate["slide_a_path"]).resolve()),
                    str(Path(candidate["slide_b_path"]).resolve()),
                    str((out_dir / "dedupe" / "semantic_candidates.json").resolve()),
                ],
                "output_paths": [str(output_path)],
                "allowed_write_paths": [str(output_path)],
                "required_schema": {
                    "same_slide": "boolean",
                    "reasoning": "string",
                    "confidence": "number",
                },
                "validation_rules": [
                    {"type": "json_fields", "required": ["same_slide", "reasoning", "confidence"]},
                    {"type": "allowed_writes"},
                ],
            }
        )
    return tasks


def write_disabled_embedding_artifacts(out_dir: Path, cfg: dict[str, Any], *, warning: str | None = None) -> dict[str, Any]:
    emb_cfg = embedding_config(cfg)
    cache_root = out_dir / str(emb_cfg.get("cache_dir", "embeddings"))
    manifest = {
        "enabled": False,
        "provider": emb_cfg.get("provider", "local_siglip"),
        "model": emb_cfg.get("model", "google/siglip-base-patch16-224"),
        "warning": warning or "embeddings.enabled is false",
    }
    write_json(cache_root / "embedding_manifest.json", manifest)
    write_json(out_dir / "dedupe" / "semantic_candidates.json", [])
    write_json(out_dir / "dedupe" / "agent_review_tasks.json", [])
    return {"semantic_candidate_count": 0, "semantic_review_task_count": 0, "embedding_warning": manifest["warning"]}


def run_semantic_dedupe_artifacts(
    out_dir: Path,
    cfg: dict[str, Any],
    slide_paths: list[Path],
    dedupe_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    emb_cfg = embedding_config(cfg)
    if not bool(emb_cfg.get("enabled", False)):
        return write_disabled_embedding_artifacts(out_dir, cfg)
    excluded_pairs = {
        tuple(sorted([str(row["time"]), str(row["kept_time"])]))
        for row in dedupe_rows
        if row.get("decision") == "duplicate"
    }
    try:
        rows = compute_slide_embedding_cache(slide_paths, out_dir, cfg)
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        return write_disabled_embedding_artifacts(out_dir, cfg, warning=str(exc))
    candidates = semantic_candidates_from_embeddings(
        rows,
        threshold=float(emb_cfg.get("similarity_threshold", 0.92)),
        max_candidates=int(emb_cfg.get("candidate_limit", 200)),
        excluded_pairs=excluded_pairs,
    )
    tasks = semantic_review_tasks(out_dir, candidates)
    write_json(out_dir / "dedupe" / "semantic_candidates.json", candidates)
    write_json(out_dir / "dedupe" / "agent_review_tasks.json", tasks)
    return {
        "semantic_candidate_count": len(candidates),
        "semantic_review_task_count": len(tasks),
        "embedding_warning": None,
    }
