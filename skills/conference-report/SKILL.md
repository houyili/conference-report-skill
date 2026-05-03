---
name: conference-report
description: Turn conference replay URLs or local videos into talk-level Chinese image-text research reports. Use when the user provides an ICLR, SlidesLive, YouTube, conference virtual page, replay URL, or local video and wants ASR timelines, slide screenshots, deduped slide intervals, schedule-aware talk segmentation, per-talk material bundles, or final Markdown reports grounded in PPT images plus speaker transcript.
---

# Conference Report

Use this skill for long conference replays that may contain multiple oral talks, keynotes, panels, Q&A sections, breaks, poster intervals, and repeated slides.

## Quick Start

Use-stage runs must use the globally installed CLI, not a source checkout fallback.

Resolve the CLI in this order:

1. If `CONFERENCE_REPORT_CLI` is set, use that absolute path after confirming it runs with `--help`.
2. Otherwise try `command -v conference-report` and use the command found on `PATH`.
3. If the agent exposes this installed skill directory, read `<installed-skill-dir>/.local/cli-path.txt` beside this `SKILL.md`; the installer writes the user's local absolute CLI path there when the global skill copy is installed or upgraded.

```bash
CLI="${CONFERENCE_REPORT_CLI:-$(command -v conference-report 2>/dev/null || true)}"
# Run this from the installed skill directory, or replace .local/cli-path.txt with its absolute path.
if [ -z "$CLI" ] && [ -f ".local/cli-path.txt" ]; then
  CLI="$(cat .local/cli-path.txt)"
fi
"$CLI" --help
```

If no CLI path can be resolved, or the resolved command fails `--help`, stop and tell the user the installed CLI is not visible to this agent shell. Ask them to set `CONFERENCE_REPORT_CLI`, restart the agent session, expose the Python environment's script directory on the agent runtime `PATH`, or upgrade the global skill with the installer so `.local/cli-path.txt` is written. Do not silently fall back to `python -m conference_report.cli` or a repository `.venv` during normal use.

Then run:

```bash
"$CLI" build "$URL" \
  --out outputs/<run-name> \
  --config config.example.yaml \
  --cookies-from-browser chrome
```

Developer-only source checkout debugging may use the package module form, but this is not a use-stage path:

```bash
python -m conference_report.cli build "$URL" \
  --out outputs/<run-name> \
  --config config.example.yaml
```

Use `--dry-run-report` only when the user explicitly wants evidence bundles instead of final reports.

## Pipeline

Run stages in order when debugging:

1. `ingest`: save metadata, subtitles, and authorized page dumps with `yt-dlp`.
2. `asr`: prefer platform subtitles; preserve audio/WAV when `asr.save_audio` is enabled; fall back to local `faster-whisper` or OpenAI transcription if configured.
3. `slides`: prefer slide metadata; otherwise extract screenshots from video.
4. `dedupe`: preserve originals, cluster repeated slides, and record `main_interval` plus `all_intervals`.
5. `segment`: parse the schedule first, align actual talk starts to transcript cues, and skip coffee/poster/lunch/break segments.
6. `report`: create per-talk evidence, then write final reports with a model/agent writer backend.
7. `validate`: check timeline monotonicity, talk packaging, and Markdown image links.

## Output Contract

Each run directory should contain:

- `asr/timeline.txt`: `[HH:MM:SS.mmm] text`
- `raw/audio/` and `asr/audio/`: preserved source audio/media and 16 kHz WAV when `asr.save_audio: true`
- `slides_original/`: original screenshots, never deleted during dedupe
- `slides_dedup/`: representative slide PNGs
- `dedup_groups.json`: visual slide clusters with provenance and repeated intervals
- `slide_intervals.json/csv`: chronological slide intervals
- `segmentation/talks.json`: talk/keynote/panel boundaries and confidence
- `segmentation/review.html`: segmentation review
- `talks/<talk_slug>/`: one material bundle per reportable talk
- `talks/<talk_slug>/evidence.json`: OCR plus ASR evidence per reportable slide
- `talks/<talk_slug>/report_writer_prompt.md`: writer instructions
- `reports/<talk_slug>.md`: final report or clearly marked evidence bundle

## Report Rules

- A final report must cover exactly one talk/keynote/panel.
- Required sections: `摘要`, `核心 Findings / Experiments / Insights`, `逐页 PPT 解读`, and `QA`.
- Each slide section must preserve image Markdown and time range, then explain the slide by combining visible PPT content with the matching ASR window.
- Write Chinese explanatory prose while preserving English technical terms.
- Stay grounded. If PPT, ASR, or OCR is ambiguous, write `不确定` or `ASR 可能错误`; do not add external paper knowledge.
- Skip low-information conference logo, blank, chair-transition, and generic cover pages unless they contain substantive talk-specific content.
- Repeated slides should appear once with repeated occurrence ranges, not as duplicate sections.

## Credentials And Access

Use user-authorized browser cookies only via `--cookies-from-browser`; do not export or commit cookies.

Generated `raw/page.html` and `raw/page_dump/*.dump` should be treated as local artifacts. The CLI redacts token-like query parameters, signed URL credentials, chat/user/session attributes, JWT-like strings, and AWS access-key-like strings; if a privacy grep finds unredacted credentials, stop and fix the sanitizer before sharing outputs.

For automated final reports, prefer the CLI credential store:

```bash
conference-report auth set openai
conference-report auth status openai
```

The CLI checks `OPENAI_API_KEY` first, then the OS credential store. If no writer backend is available, stop at evidence bundles and tell the user they are not final research reports.
