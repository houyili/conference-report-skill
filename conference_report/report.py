from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .auth import get_openai_api_key, openai_client_kwargs
from .utils import ensure_dir, find_tool, parse_time_seconds, read_json, write_json


WRITER_MODES = {"auto", "agent", "openai", "evidence"}
REPORT_REQUIRED_SECTIONS = ["摘要", "核心 Findings / Experiments / Insights", "逐页 PPT 解读", "QA"]

BOILERPLATE_TOKENS = {
    "iclr",
    "international",
    "conference",
    "learning",
    "representations",
    "oral",
    "presentation",
    "session",
}
CHAIR_INTRO_PATTERNS = (
    "our last paper",
    "will be presented by",
    "let's get started",
    "we will have",
    "session chair",
)
BREAK_SLIDE_PATTERNS = (
    "coffee break",
    "lunch break",
    "poster session",
    "poster break",
    "registration",
    "intermission",
)


def image_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def markdown_image_path(report_path: Path, image_path: Path) -> str:
    rel = os.path.relpath(image_path.resolve(), report_path.parent.resolve())
    return quote(rel.replace("\\", "/"))


def transcript_text(path: Path, limit: int | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    return text[:limit] if limit else text


def call_responses(model: str, content: list[dict[str, Any]]) -> str:
    from openai import OpenAI

    client = OpenAI(**openai_client_kwargs())
    response = client.responses.create(model=model, input=[{"role": "user", "content": content}])
    return response.output_text


def interval_ranges(interval: dict[str, Any]) -> list[tuple[str, str]]:
    occurrences = interval.get("all_intervals") or [interval]
    return [(str(item["start_time"]), str(item["end_time"])) for item in occurrences]


def compact_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].strip() + "..."


def clean_ocr_text(text: str, max_chars: int = 1400) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 4:
            continue
        alnum = sum(ch.isalnum() for ch in line)
        if alnum / max(1, len(line)) < 0.35:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return compact_text(" ".join(lines), max_chars)


def clean_asr_text(text: str, max_chars: int = 1400) -> str:
    text = strip_timestamps(text)
    text = re.sub(r"\bOccurrence\s+\d+\s*\([^)]*\)\s*", "", text)
    return compact_text(text, max_chars)


def text_tokens(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text)]


def informative_tokens(text: str) -> list[str]:
    return [token for token in text_tokens(text) if token not in BOILERPLATE_TOKENS]


def title_overlap(title: str, text: str) -> int:
    title_tokens = {token for token in informative_tokens(title) if len(token) >= 4}
    body_tokens = set(text_tokens(text))
    return len(title_tokens & body_tokens)


def low_information_reason(title: str, ocr_text: str, asr_text: str) -> str | None:
    ocr_tokens = text_tokens(ocr_text)
    info_tokens = informative_tokens(ocr_text)
    has_title = title_overlap(title, ocr_text) >= 2
    ocr_lower = ocr_text.lower()
    asr_lower = asr_text.lower()
    has_conference_branding = "iclr" in ocr_lower or "international conference" in ocr_lower
    has_break_label = any(pattern in ocr_lower for pattern in BREAK_SLIDE_PATTERNS)
    if has_break_label and not has_title:
        return "break/poster/intermission slide"
    has_only_branding = has_conference_branding and len(info_tokens) <= 3 and not has_title
    chair_intro_only = has_only_branding and any(pattern in asr_lower for pattern in CHAIR_INTRO_PATTERNS)
    if chair_intro_only:
        return "conference branding with chair transition audio"
    if has_only_branding:
        return "conference branding slide"
    if len(ocr_tokens) <= 3 and not has_title and len(informative_tokens(asr_text)) <= 18:
        return "blank or OCR-noise transition slide"
    return None


def strip_timestamps(timeline: str) -> str:
    lines = []
    for line in timeline.splitlines():
        line = re.sub(r"^\[\d\d:\d\d:\d\d\.\d\d\d\]\s*", "", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines)


def first_sentenceish(text: str, max_chars: int) -> str:
    text = compact_text(text, max_chars * 2)
    pieces = re.split(r"(?<=[.!?。！？])\s+", text)
    for piece in pieces:
        piece = piece.strip()
        if len(piece) >= 24:
            return compact_text(piece, max_chars)
    return compact_text(text, max_chars)


def infer_slide_role(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ["conclusion", "takeaway", "summary", "guidance", "future work"]):
        return "总结页"
    if any(word in lowered for word in ["result", "evaluation", "experiment", "benchmark", "table", "figure", "finding"]):
        return "实验与结果页"
    if any(word in lowered for word in ["method", "methodology", "pipeline", "algorithm", "step", "architecture"]):
        return "方法页"
    if any(word in lowered for word in ["motivation", "problem", "question", "why", "diagnosis", "challenge"]):
        return "问题动机页"
    if any(word in lowered for word in ["title", "oral presentation"]) or len(text) < 220:
        return "标题或过渡页"
    return "论证展开页"


def ocr_slide_text(image: Path, cache_path: Path) -> str:
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")
    tesseract = find_tool("tesseract")
    if tesseract is None:
        return ""
    try:
        proc = subprocess.run(
            [tesseract, str(image), "stdout", "-l", "eng", "--psm", "6"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return ""
    text = proc.stdout if proc.returncode == 0 else ""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


def extractive_slide_note(*, title: str, time_label: str, ocr_text: str, asr_text: str) -> str:
    ppt = clean_ocr_text(ocr_text, 900)
    asr = clean_asr_text(asr_text, 1100)
    role = infer_slide_role(f"{ppt} {asr}")
    ppt_focus = first_sentenceish(ppt, 260) if ppt else "PPT 图像中的文字无法由本地 OCR 稳定读取"
    asr_focus = first_sentenceish(asr, 360) if asr else "对应时间窗缺少足够 ASR"
    parts = []
    if ppt:
        parts.append(f"**PPT内容**：OCR 识别到这一页的可见文本主要是：{ppt}")
    else:
        parts.append("**PPT内容**：本地 OCR 没有稳定识别出可用文字，请以图片本身为准。")
    if asr:
        parts.append(f"**演讲者说明**：在 `{time_label}` 附近，ASR 记录到演讲者主要说：{asr}")
    else:
        parts.append(f"**演讲者说明**：`{time_label}` 这个时间窗内没有抽到足够 ASR 文本。")
    if ppt and asr:
        parts.append(
            f"**合并解读**：这是一张{role}。PPT 侧的核心线索是“{ppt_focus}”；演讲者在同一时间窗把它展开为“{asr_focus}”。"
            "因此整理报告时，应把这一页写成“可见 slide 证据 + 口头解释”的组合：先引用 PPT 上的术语、数字或图表，再用 ASR 说明它在论证中的作用。"
            "由于这是 OCR + ASR 的本地 fallback，专有名词和数字仍需要优先对照原图和原始 transcript 校验。"
        )
    else:
        parts.append(
            "**合并解读**：当前证据不足以可靠扩写，只能保守地把这页作为原始素材索引；后续使用 vision 模型生成时可补全更精确的页面解读。"
        )
    return "\n\n".join(parts)


def evidence_slide_note(*, ocr_text: str, asr_text: str) -> str:
    ppt = clean_ocr_text(ocr_text, 900)
    asr = clean_asr_text(asr_text, 1100)
    parts = []
    if ppt:
        parts.append(f"**PPT证据**：{ppt}")
    else:
        parts.append("**PPT证据**：OCR 未稳定识别出可用文字，请直接查看截图。")
    if asr:
        parts.append(f"**ASR证据**：{asr}")
    else:
        parts.append("**ASR证据**：该时间窗没有足够 transcript。")
    return "\n\n".join(parts)


def interval_time_label(interval: dict[str, Any]) -> str:
    main = interval.get("main_interval") or interval
    ranges = interval_ranges(interval)
    label = f"{ranges[0][0]} - {ranges[0][1]}"
    if len(ranges) > 1:
        label += f"; main: {main['start_time']} - {main['end_time']}"
        label += "; occurrences: " + ", ".join(f"{start}-{end}" for start, end in ranges)
    return label


def slide_window_text(timeline: str, ranges: list[tuple[str, str]], max_chars: int) -> str:
    parsed = []
    for line in timeline.splitlines():
        match = re.match(r"\[(\d\d:\d\d:\d\d\.\d\d\d)\]\s*(.*)", line)
        if match:
            parsed.append((parse_time_seconds(match.group(1)), line))
    blocks = []
    for index, (start, end) in enumerate(ranges, start=1):
        start_s = parse_time_seconds(start)
        end_s = parse_time_seconds(end)
        lines = [line for seconds, line in parsed if start_s <= seconds < end_s]
        if lines:
            blocks.append(f"Occurrence {index} ({start} - {end})\n" + "\n".join(lines))
    text = "\n\n".join(blocks) if blocks else timeline[:max_chars]
    return text[:max_chars]


def write_report_writer_prompt(talk_dir: Path, metadata: dict[str, Any], *, skipped_count: int) -> None:
    prompt = f"""# Report Writer Prompt

你负责把本 talk 的素材写成一份中文图文研究报告。

## Talk

- Title: {metadata['title']}
- Speakers: {', '.join(metadata.get('speakers', []))}
- Time: {metadata.get('aligned_start')} - {metadata.get('aligned_end')}

## 输入文件

- `metadata.json`: talk 元信息和网页 abstract
- `timeline.txt`: 该 talk 的 ASR transcript
- `slide_intervals.json`: 去重后的 PPT 页面、主时间段和重复出现区间
- `slides/`: 每一页代表 PPT 截图
- `evidence.json`: 每页 OCR + 对应 ASR 证据
- `skipped_slides.json`: 被跳过的低信息量页面，共 {skipped_count} 张
- `slide_cognition/`: agent/VLM 对每页截图的持久化视觉认知 JSON（如果 host agent 已执行）
- `qa/qa_pairs.json`: agent 合并 transcript 后形成的问答对（如果 host agent 已执行）

## 写作规则

1. 只依据 PPT 截图、`timeline.txt`、`slide_intervals.json`、`metadata.json`，不要补充外部知识。
2. 输出中文，技术术语保留英文。
3. 不要逐字转写 OCR/ASR。要先理解每一页在 talk 里的作用，再写解释。
4. 每一页解释必须同时参考 PPT 可见内容和演讲者在对应时间窗说的话。
5. ASR 明显错误时，按 PPT 和上下文保守纠正；不确定就写“不确定，ASR 可能错误”。
6. 省略 conference logo、空白页、主持人纯转场页，不要在正文中解释这些页面。
7. 报告结构固定为：摘要、核心 Findings / Experiments / Insights、逐页 PPT 解读、QA。
8. 逐页章节中保留图片 Markdown、时间范围，并写 1-3 段有信息量的解释。
9. 如果存在 `slide_cognition/` 和 `qa/qa_pairs.json`，报告必须消费这些文件；不要把 OCR/ASR 机械填进报告。
10. 每个主要 finding 要能追溯到具体 slide/time/evidence；没有证据的 claim 不要写。
"""
    (talk_dir / "report_writer_prompt.md").write_text(prompt, encoding="utf-8")


def build_slide_evidence(talk_dir: Path, metadata: dict[str, Any], intervals: list[dict[str, Any]], timeline: str, cfg: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    ocr_dir = ensure_dir(talk_dir / "ocr")
    evidence: list[dict[str, str]] = []
    skipped_slides: list[dict[str, str]] = []
    max_chars = int(cfg["report"].get("max_transcript_chars_per_slide", 2500))
    for idx, interval in enumerate(intervals, start=1):
        image = Path(interval.get("talk_slide_path") or interval["representative_path"])
        time_label = interval_time_label(interval)
        local_text = slide_window_text(timeline, interval_ranges(interval), max_chars)
        ocr_text = ocr_slide_text(image, ocr_dir / f"{idx:04d}_{image.stem}.txt")
        skip_reason = low_information_reason(metadata["title"], ocr_text, local_text)
        row = {
            "slide_index": str(idx),
            "time": time_label,
            "image": str(image),
            "ocr_text": clean_ocr_text(ocr_text, 1800),
            "asr_text": clean_asr_text(local_text, 1800),
            "role": infer_slide_role(f"{ocr_text} {local_text}"),
        }
        if skip_reason:
            skipped_slides.append({"time": time_label, "image": str(image), "reason": skip_reason})
            continue
        evidence.append(row)
    write_json(talk_dir / "evidence.json", evidence)
    write_json(talk_dir / "skipped_slides.json", skipped_slides)
    write_report_writer_prompt(talk_dir, metadata, skipped_count=len(skipped_slides))
    return evidence, skipped_slides


def write_evidence_bundle_report(report_path: Path, metadata: dict[str, Any], evidence: list[dict[str, str]], skipped_slides: list[dict[str, str]]) -> Path:
    lines = [
        f"# {metadata['title']}",
        "",
        "> 状态：这是 evidence bundle，不是最终研究报告。当前环境没有可用 writer backend/API key，所以这里只整理 PPT 与 ASR 证据；最终报告应由 LLM/agent 基于本证据包撰写。",
        "",
        "## 基础信息",
        "",
        f"- Speakers: {', '.join(metadata.get('speakers', []))}",
        f"- Time: {metadata.get('aligned_start')} - {metadata.get('aligned_end')}",
    ]
    if metadata.get("abstract"):
        lines.extend(["", "## 网页 Abstract", "", str(metadata["abstract"])])
    if skipped_slides:
        lines.extend(["", f"> 已省略 {len(skipped_slides)} 张低信息量封面/会场 logo/过渡页；原图和原因保留在 talk 素材包的 `skipped_slides.json`。"])
    lines.extend(["", "## 逐页证据", ""])
    for idx, item in enumerate(evidence, start=1):
        image = Path(item["image"])
        lines.extend([
            f"### 第 {idx} 张 PPT ({item['time']})",
            "",
            f"![slide]({markdown_image_path(report_path, image)})",
            "",
            f"- Page role guess: {item['role']}",
            f"- PPT evidence: {item['ocr_text'] or 'OCR 未稳定识别出可用文字，请直接查看截图。'}",
            f"- ASR evidence: {item['asr_text'] or '该时间窗没有足够 transcript。'}",
            "",
        ])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def agent_slide_cognition_tasks(talk_dir: Path, metadata: dict[str, Any], evidence: list[dict[str, str]]) -> list[dict[str, Any]]:
    output_dir = ensure_dir(talk_dir / "slide_cognition")
    tasks: list[dict[str, Any]] = []
    for idx, item in enumerate(evidence, start=1):
        output_path = (output_dir / f"{idx:04d}.json").resolve()
        image_path = Path(item["image"]).resolve()
        tasks.append(
            {
                "task_id": f"slide-cognition:{metadata['slug']}:{idx:04d}",
                "stage": "slide_cognition",
                "slug": str(metadata["slug"]),
                "title": str(metadata["title"]),
                "slide_index": idx,
                "time": item["time"],
                "input_paths": [
                    str((talk_dir / "metadata.json").resolve()),
                    str((talk_dir / "timeline.txt").resolve()),
                    str((talk_dir / "evidence.json").resolve()),
                    str(image_path),
                ],
                "output_paths": [str(output_path)],
                "allowed_write_paths": [str(output_path)],
                "required_schema": {
                    "visual_summary": "string",
                    "speaker_intent": "string",
                    "main_claims": "array",
                    "method_details": "array",
                    "experiment_or_result": "array",
                    "numbers_and_entities": "array",
                    "asr_corrections": "array",
                    "uncertainties": "array",
                    "confidence": "number",
                },
                "instructions": [
                    "Read the slide image, evidence.json row, metadata, and nearby timeline before writing.",
                    "If the host has VLM/image understanding, inspect the image directly. If not, say so in uncertainties.",
                    "Output semantic understanding: visual_summary, speaker_intent, claims, method details, results, numbers/entities.",
                    "Do not copy OCR/ASR into the JSON as the main answer; use OCR/ASR only as evidence.",
                ],
                "validation_rules": [
                    {
                        "type": "json_fields",
                        "required": [
                            "visual_summary",
                            "speaker_intent",
                            "main_claims",
                            "method_details",
                            "experiment_or_result",
                            "numbers_and_entities",
                            "asr_corrections",
                            "uncertainties",
                            "confidence",
                        ],
                    },
                    {"type": "semantic_depth", "rule": "main_claims and speaker_intent must be explanatory, not OCR/ASR copies."},
                    {"type": "allowed_writes"},
                ],
            }
        )
    return tasks


def agent_qa_task(talk_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    output_path = (ensure_dir(talk_dir / "qa") / "qa_pairs.json").resolve()
    return {
        "task_id": f"qa-detection:{metadata['slug']}",
        "stage": "qa_detection",
        "slug": str(metadata["slug"]),
        "title": str(metadata["title"]),
        "input_paths": [
            str((talk_dir / "metadata.json").resolve()),
            str((talk_dir / "timeline.txt").resolve()),
            str((talk_dir / "evidence.json").resolve()),
        ],
        "output_paths": [str(output_path)],
        "allowed_write_paths": [str(output_path)],
        "required_schema": {
            "qa_pairs": "array",
            "uncertainties": "array",
            "confidence": "number",
        },
        "instructions": [
            "Read the end of timeline.txt and evidence.json, then merge adjacent transcript fragments into real question/answer pairs.",
            "Each qa_pairs item must include question, answer, time_range, evidence_quotes, and confidence.",
            "Do not list transcript fragments as QA. If no reliable pair exists, leave qa_pairs empty and explain why in uncertainties.",
        ],
        "validation_rules": [
            {"type": "json_fields", "required": ["qa_pairs", "uncertainties", "confidence"]},
            {"type": "qa_pair_schema", "required": ["question", "answer", "time_range", "evidence_quotes", "confidence"]},
            {"type": "allowed_writes"},
        ],
    }


def agent_grounding_task(talk_dir: Path, report_path: Path, metadata: dict[str, Any], *, dependency_outputs: list[str] | None = None) -> dict[str, Any]:
    output_path = (report_path.parent / f"{metadata['slug']}.grounding.json").resolve()
    dependencies = [str(report_path.resolve())]
    if dependency_outputs:
        dependencies.extend(dependency_outputs)
    return {
        "task_id": f"grounding-review:{metadata['slug']}",
        "stage": "grounding_review",
        "slug": str(metadata["slug"]),
        "title": str(metadata["title"]),
        "input_paths": [
            str((talk_dir / "metadata.json").resolve()),
            str((talk_dir / "evidence.json").resolve()),
        ],
        "dependency_output_paths": dependencies,
        "output_paths": [str(output_path)],
        "allowed_write_paths": [str(output_path)],
        "required_schema": {
            "checked_claims": "array",
            "unsupported_claims": "array",
            "missing_coverage": "array",
            "template_or_style_issues": "array",
            "requires_revision": "boolean",
            "confidence": "number",
        },
        "instructions": [
            "Review the report at claim level against evidence.json, slide_cognition outputs, qa_pairs, and images.",
            "checked_claims must list each important claim with evidence_refs and support status.",
            "Set requires_revision=true if the report is template-like, unsupported, missing major slide coverage, or misuses QA fragments.",
        ],
        "validation_rules": [
            {
                "type": "json_fields",
                "required": [
                    "checked_claims",
                    "unsupported_claims",
                    "missing_coverage",
                    "template_or_style_issues",
                    "requires_revision",
                    "confidence",
                ],
            },
            {"type": "claim_level_review"},
            {"type": "allowed_writes"},
        ],
    }


def agent_report_task(
    talk_dir: Path,
    report_path: Path,
    metadata: dict[str, Any],
    *,
    cognition_tasks: list[dict[str, Any]],
    qa_task: dict[str, Any],
) -> dict[str, Any]:
    dependency_outputs = [output for task in cognition_tasks for output in task["output_paths"]]
    dependency_outputs.extend(qa_task["output_paths"])
    return {
        "task_id": f"report:{metadata['slug']}",
        "stage": "report_write",
        "slug": str(metadata["slug"]),
        "title": str(metadata["title"]),
        "talk_dir": str(talk_dir.resolve()),
        "slides_dir": str((talk_dir / "slides").resolve()),
        "prompt_path": str((talk_dir / "report_writer_prompt.md").resolve()),
        "evidence_path": str((talk_dir / "evidence.json").resolve()),
        "metadata_path": str((talk_dir / "metadata.json").resolve()),
        "timeline_path": str((talk_dir / "timeline.txt").resolve()),
        "report_path": str(report_path.resolve()),
        "input_paths": [
            str((talk_dir / "report_writer_prompt.md").resolve()),
            str((talk_dir / "evidence.json").resolve()),
            str((talk_dir / "metadata.json").resolve()),
            str((talk_dir / "timeline.txt").resolve()),
            str((talk_dir / "slides").resolve()),
        ],
        "dependency_output_paths": dependency_outputs,
        "output_paths": [str(report_path.resolve())],
        "allowed_write_paths": [str(report_path.resolve())],
        "required_sections": REPORT_REQUIRED_SECTIONS,
        "validation_rules": [
            {"type": "exists", "paths": "output_paths"},
            {"type": "markdown_required_sections", "sections": REPORT_REQUIRED_SECTIONS},
            {"type": "markdown_image_links_exist"},
            {"type": "consume_slide_cognition_and_qa_pairs"},
            {"type": "report_quality"},
            {"type": "allowed_writes"},
        ],
        "quality_contract": [
            "Read every dependency_output_paths item before writing.",
            "Use slide_cognition main_claims, numbers_and_entities, speaker_intent, and qa_pairs where available.",
            "Do not use a repeated page template or copy OCR/ASR paragraphs as the report body.",
            "Each major finding must include or imply a concrete slide/time/evidence anchor.",
        ],
        "done_condition": "Write exactly one quality-gated Markdown report to output_paths[0] after dependency_output_paths exist; it must pass validate --phase report-quality.",
    }


def resolve_writer_mode(cfg: dict[str, Any], writer: str | None, dry_run: bool | None) -> str:
    if dry_run is True:
        return "evidence"
    mode = writer or str(cfg.get("report", {}).get("writer", "auto"))
    if mode not in WRITER_MODES:
        raise ValueError(f"Unsupported writer mode: {mode}")
    if mode == "auto":
        return "openai" if bool(get_openai_api_key()) else "evidence"
    return mode


def require_openai_writer_key() -> None:
    if not get_openai_api_key():
        raise SystemExit(
            "OpenAI API key is required for --writer openai. "
            "Use --writer agent inside Codex/Claude Code/Antigravity/OpenClaw, "
            "--writer evidence for evidence bundles, or set OPENAI_API_KEY/keyring for pure CLI writing."
        )


def generate_talk_report(talk_dir: Path, reports_dir: Path, cfg: dict[str, Any], *, writer_mode: str) -> tuple[Path, dict[str, list[dict[str, Any]]]]:
    metadata = read_json(talk_dir / "metadata.json")
    intervals = read_json(talk_dir / "slide_intervals.json")
    timeline = transcript_text(talk_dir / "timeline.txt")
    report_path = ensure_dir(reports_dir) / f"{metadata['slug']}.md"
    model = cfg["api"].get("model", "gpt-5.1")
    notes_dir = ensure_dir(talk_dir / "notes")
    evidence, skipped_slides = build_slide_evidence(talk_dir, metadata, intervals, timeline, cfg)
    if writer_mode == "agent":
        cognition_tasks = agent_slide_cognition_tasks(talk_dir, metadata, evidence)
        qa_task = agent_qa_task(talk_dir, metadata)
        report_task = agent_report_task(talk_dir, report_path, metadata, cognition_tasks=cognition_tasks, qa_task=qa_task)
        grounding_task = agent_grounding_task(
            talk_dir,
            report_path,
            metadata,
            dependency_outputs=list(report_task["dependency_output_paths"]),
        )
        return report_path, {
            "slide_cognition": cognition_tasks,
            "qa_detection": [qa_task],
            "report_write": [report_task],
            "grounding_review": [grounding_task],
        }
    if writer_mode == "evidence":
        return write_evidence_bundle_report(report_path, metadata, evidence, skipped_slides), {}
    if writer_mode != "openai":
        raise ValueError(f"Unsupported writer mode: {writer_mode}")

    slide_notes: list[dict[str, str]] = []
    for idx, item in enumerate(evidence, start=1):
        image = Path(item["image"])
        prompt = (
            "你是严谨的会议报告整理助手。请只根据这一页 PPT 图像、OCR 文本和对应 ASR 片段写中文解读，英文术语保持英文。"
            "不要逐字复述 OCR/ASR；请解释这页在整场 talk 的论证作用。"
            "如果 ASR 或图片不足以判断，请明确写不确定。输出 1-3 段，不要自我发散。\n\n"
            f"Talk: {metadata['title']}\n"
            f"Time: {item['time']}\n"
            f"OCR:\n{item['ocr_text']}\n\n"
            f"ASR:\n{item['asr_text']}"
        )
        note = call_responses(model, [{"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": image_data_url(image)}])
        safe_time = item["time"].split(";")[0].replace(":", "-")
        note_path = notes_dir / f"{idx:04d}_{safe_time}.md"
        note_path.write_text(note, encoding="utf-8")
        slide_notes.append({"time": item["time"], "image": item["image"], "note": note})

    overview_prompt = (
        "请根据下面逐页 notes，为整场报告写中文研究报告的摘要与核心 Findings/Experiments/Insights。"
        "必须忠于材料，不要补充外部知识。英文术语保持英文。"
        "请输出三个 Markdown 二级标题：“摘要”、“核心 Findings / Experiments / Insights”、“QA”。"
        "如果没有 QA 证据，在 QA 部分写“未检测到明确 QA 内容”。不要输出逐页内容。\n\n"
        f"Title: {metadata['title']}\nSpeakers: {metadata.get('speakers', [])}\n\n"
        + "\n\n".join(f"[{item['time']}]\n{item['note']}" for item in slide_notes)
    )
    overview = call_responses(model, [{"type": "input_text", "text": overview_prompt}])

    lines = [f"# {metadata['title']}", "", overview.strip(), ""]
    if skipped_slides:
        lines.extend([f"> 已省略 {len(skipped_slides)} 张低信息量封面/会场 logo/过渡页；原图和原因保留在 `talks/{metadata['slug']}/skipped_slides.json`。", ""])
    lines.extend(["## 逐页 PPT 解读", ""])
    for idx, item in enumerate(slide_notes, start=1):
        image = Path(item["image"])
        lines.extend([
            f"### 第 {idx} 张 PPT ({item['time']})",
            "",
            f"![slide]({markdown_image_path(report_path, image)})",
            "",
            item["note"].strip(),
            "",
        ])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path, {}


def generate_reports(out_dir: Path, cfg: dict[str, Any], *, dry_run: bool | None = None, writer: str | None = None) -> list[Path]:
    writer_mode = resolve_writer_mode(cfg, writer, dry_run)
    if writer_mode == "openai":
        require_openai_writer_key()
    talks_root = out_dir / "talks"
    reports_dir = ensure_dir(out_dir / "reports")
    report_paths: list[Path] = []
    agent_tasks: dict[str, list[dict[str, Any]]] = {
        "slide_cognition": [],
        "qa_detection": [],
        "report_write": [],
        "grounding_review": [],
    }
    for talk_dir in sorted(path for path in talks_root.iterdir() if path.is_dir()):
        report_path, task_bundle = generate_talk_report(talk_dir, reports_dir, cfg, writer_mode=writer_mode)
        report_paths.append(report_path)
        for stage, tasks in task_bundle.items():
            agent_tasks.setdefault(stage, []).extend(tasks)

    task_manifest_paths = {
        "slide_cognition": out_dir / "agent_slide_cognition_tasks.json",
        "qa_detection": out_dir / "agent_qa_tasks.json",
        "report_write": out_dir / "agent_report_tasks.json",
        "grounding_review": out_dir / "agent_grounding_tasks.json",
    }
    if writer_mode == "agent":
        for stage, path in task_manifest_paths.items():
            write_json(path, agent_tasks.get(stage, []))
    else:
        for path in task_manifest_paths.values():
            if path.exists():
                path.unlink()

    planned_reports = [str(path.resolve()) for path in report_paths]
    completed_reports = [path for path in planned_reports if Path(path).exists()]
    pending_reports = [path for path in planned_reports if not Path(path).exists()]
    report_manifest_paths = completed_reports if writer_mode == "agent" else planned_reports

    manifest = {
        "dry_run": writer_mode == "evidence",
        "writer_mode": writer_mode,
        "final_reports": writer_mode == "openai",
        "mode": {"agent": "agent_subagents", "evidence": "evidence_bundle", "openai": "openai_responses"}[writer_mode],
        "reports": report_manifest_paths,
        "planned_reports": planned_reports,
        "completed_reports": completed_reports,
        "pending_reports": pending_reports,
    }
    if writer_mode == "agent":
        manifest["task_manifests"] = {stage: str(path.resolve()) for stage, path in task_manifest_paths.items()}
        manifest["tasks_manifest"] = str(task_manifest_paths["report_write"].resolve())
        manifest["task_count"] = sum(len(tasks) for tasks in agent_tasks.values())
        manifest["task_counts"] = {stage: len(tasks) for stage, tasks in agent_tasks.items()}
    write_json(out_dir / "reports_manifest.json", manifest)
    return report_paths
