# Conference Report Skill

[![CI](https://github.com/houyili/conference-report-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/houyili/conference-report-skill/actions/workflows/ci.yml)

Turn long conference replay URLs or local videos into talk-level Chinese image-text research reports grounded in slide screenshots and speaker transcript.

The project is a reusable CLI plus a Codex/agent skill. It is designed for ICLR virtual pages, SlidesLive pages, YouTube/ordinary video URLs, and local video files. A single replay can contain multiple oral talks, keynotes, panels, Q&A sections, and breaks; the pipeline keeps those separated.

## What It Produces

```text
raw/                         # metadata, page dumps, media, subtitles
asr/timeline.txt             # [HH:MM:SS.mmm] transcript text
asr/timeline.jsonl           # structured ASR rows
slides_original/             # original [time].png screenshots
slides_dedup/                # representative slide PNGs
dedup_groups.json            # provenance-preserving visual clusters
slide_intervals.json/csv     # slide start/end and repeated occurrence intervals
segmentation/talks.json      # talk/keynote/panel boundaries
segmentation/review.html     # human review page
talks/<talk_slug>/           # per-talk material bundle
reports/<talk_slug>.md       # final Chinese report, or evidence bundle if no writer backend
manifest.json
```

Final reports follow this structure:

- 摘要
- 核心 Findings / Experiments / Insights
- 逐页 PPT 解读 with image, time range, and grounded explanation
- QA, when evidence exists

The report writer is intentionally conservative: it should combine visible PPT content with ASR evidence, keep English technical terms in English, and write `不确定` when the evidence is insufficient.

## Dependencies

Runtime requirements:

| Dependency | Version / range | Purpose |
| --- | --- | --- |
| Python | `>=3.10` | CLI runtime |
| ffmpeg + ffprobe | `>=6` recommended | audio extraction and video frame extraction |
| yt-dlp | `>=2025.1.15` | metadata, subtitles, and media access |
| Pillow | `>=10,<13` | image loading and slide dedupe |
| PyYAML | `>=6,<7` | config and manual segments |
| beautifulsoup4 | `>=4.12,<5` | conference schedule parsing |
| keyring | `>=25,<26` | macOS Keychain / OS credential store access |
| openai | `>=2,<3` | OpenAI Responses and transcription APIs |

Optional:

| Dependency | Version / range | Purpose |
| --- | --- | --- |
| faster-whisper | `>=1.1,<2` | local ASR fallback |
| tesseract | `>=5` recommended | local OCR evidence bundles |
| lxml | `>=5,<7` | faster HTML parsing |
| pytest | `>=8,<9` | tests |

Known-compatible pinned versions are listed in `requirements.lock`. Normal users should install from `pyproject.toml` or `requirements.txt`; the lock file is a reproducibility reference, not a strict requirement.

## Install

Clone and run the guided installer:

```bash
git clone https://github.com/houyili/conference-report-skill.git
cd conference-report-skill
python3 scripts/install.py --with-local-asr
```

On macOS, the installer can guide you through Homebrew installation of `ffmpeg` and optional `tesseract`:

```bash
python3 scripts/install.py --with-local-asr --install-system-deps
```

Manual install:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[asr,dev]"
brew install ffmpeg tesseract   # macOS example
```

Linux and Windows equivalents:

```bash
# Debian/Ubuntu
sudo apt-get install ffmpeg tesseract-ocr

# Windows with Chocolatey
choco install ffmpeg tesseract
```

## System Compatibility

| System | Status | Notes |
| --- | --- | --- |
| macOS 14+ on Apple Silicon | Tested | Fresh install smoke test passed with Python 3.14, Homebrew `ffmpeg`, `ffprobe`, and `tesseract`. Key storage uses macOS Keychain through `keyring`. |
| macOS Intel | Expected | Same Homebrew dependencies; not yet tested in CI. |
| Linux x86_64 | Expected | Requires Python 3.10+, `ffmpeg`, and optionally `tesseract`. Key storage uses Secret Service / KWallet when available; otherwise use `OPENAI_API_KEY`. |
| Windows 10/11 | Expected | Requires Python 3.10+, `ffmpeg` on PATH, and optionally `tesseract`. Key storage uses Windows Credential Manager when available; otherwise use `OPENAI_API_KEY`. |

The CLI searches both the system `PATH` and the active Python environment's script directory, so `yt-dlp` installed into `.venv` is detected even when the shell has not activated the venv.

## API Key And Privacy

For final automated reports, store your own OpenAI API key in the OS credential store:

```bash
.venv/bin/conference-report auth set openai
.venv/bin/conference-report auth status openai
```

On macOS this uses Keychain through the Python `keyring` package. On Windows it uses Windows Credential Manager when available. On Linux it uses Secret Service / KWallet when configured.

You may also use an environment variable:

```bash
export OPENAI_API_KEY="<your OpenAI API key>"
```

Credential lookup order is:

1. `OPENAI_API_KEY`
2. system credential store entry under service `conference-report`, account `openai_api_key`

The repository does not require or store private API keys in files. `.env`, cookies, raw media, screenshots, subtitles, transcripts, and generated outputs are ignored by git.

For restricted conference pages, use browser cookies only when you are authorized to access the content:

```bash
.venv/bin/conference-report build "https://iclr.cc/virtual/2026/session/..." \
  --out outputs/iclr-session \
  --config config.example.yaml \
  --cookies-from-browser chrome
```

The tool asks `yt-dlp` to read cookies from your local browser session. It does not bypass access controls and should not be used on content you are not allowed to access.

## Quick Start

```bash
.venv/bin/conference-report build URL \
  --out outputs/run-name \
  --config config.example.yaml
```

Useful subcommands:

```bash
conference-report ingest URL --out outputs/run
conference-report asr URL --out outputs/run --config config.example.yaml
conference-report slides --out outputs/run --config config.example.yaml
conference-report dedupe --out outputs/run --config config.example.yaml
conference-report segment --out outputs/run --config config.example.yaml
conference-report report --out outputs/run --config config.example.yaml
conference-report validate --out outputs/run --config config.example.yaml
```

If there is no OpenAI key and `dry_run_without_key: true`, the `report` step emits evidence bundles instead of pretending they are final research reports. Evidence bundles are useful for review, but they are not finished reports.

## Manual Segments

If the conference page does not expose a schedule, the pipeline writes `segmentation/manual_segments.template.yaml`. You can also provide your own:

```bash
conference-report segment \
  --out outputs/run \
  --config config.example.yaml \
  --manual-segments examples/manual_segments/manual_segments.template.yaml
```

Breaks such as coffee, poster sessions, lunch, and registration are retained in segmentation review artifacts but do not generate reports.

## Codex Skill Install

To install the bundled skill into Codex:

```bash
python3 scripts/install_codex_skill.py
```

The skill is intentionally small. User-facing setup and dependency information lives in this README; the skill itself tells Codex how to run the pipeline and how to preserve report quality.

## Development

Run tests:

```bash
.venv/bin/python -m pytest
```

Validate the bundled skill if you have Codex's `skill-creator` tools installed:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/conference-report
```

## Current Scope

This is a v1 alpha. It is intentionally conservative:

- SlidesLive-style slide metadata is preferred when available.
- Otherwise, `ffmpeg` scene/interval screenshots are used.
- Slide dedupe preserves provenance and never deletes `slides_original/`.
- Schedule parsing is best-effort and currently strongest for ICLR-style pages.
- Report writing uses OpenAI Responses API when configured; without a key it emits evidence bundles.

Contributions that improve schedule parsers, video backends, and non-OpenAI writer adapters are welcome.
