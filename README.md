# Conference Report Skill

[![CI](https://github.com/houyili/conference-report-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/houyili/conference-report-skill/actions/workflows/ci.yml)

Turn long conference replay URLs or local videos into talk-level Chinese image-text research reports grounded in slide screenshots and speaker transcript.

The project is a reusable CLI plus a Codex/agent skill. It is designed for ICLR virtual pages, SlidesLive pages, YouTube/ordinary video URLs, and local video files. A single replay can contain multiple oral talks, keynotes, panels, Q&A sections, and breaks; the pipeline keeps those separated.

## Open-Source Usability

This project is developed as an open-source tool first. Installers, examples, defaults, and skill instructions should be usable by outside users without maintainer-specific paths, private credentials, or hidden local setup. Local maintainer runs are treated as realistic user acceptance tests; only generalized, privacy-preserving improvements belong in the repository.

## What It Produces

```text
raw/                         # metadata, page dumps, media, subtitles
raw/audio/                   # preserved source audio/media when asr.save_audio is true
asr/timeline.txt             # [HH:MM:SS.mmm] transcript text
asr/timeline.jsonl           # structured ASR rows
asr/audio/                   # 16 kHz mono WAV used for local/API ASR or audit
slides_original/             # original [time].png screenshots
slides_dedup/                # representative slide PNGs
embeddings/slides/           # optional local semantic embedding cache
dedupe/semantic_candidates.json
dedupe/agent_review_tasks.json
dedupe/agent_review_validation.json
dedupe/agent_review_apply_manifest.json
dedup_groups.json            # provenance-preserving visual clusters
slide_intervals.json/csv     # slide start/end and repeated occurrence intervals
segmentation/talks.json      # talk/keynote/panel boundaries
segmentation/review.html     # human review page
talks/<talk_slug>/           # per-talk material bundle
agent_slide_cognition_tasks.json
agent_qa_tasks.json
agent_report_tasks.json
agent_grounding_tasks.json
agent_task_validation.json
report_quality_validation.json # quality audit for agent-written reports
agent_report_revision_tasks.json
pipeline_state.json          # current agent gate and next validate/resume commands
reports/<talk_slug>.md       # final Chinese report, or evidence bundle when requested
reports/<talk_slug>.grounding.json
manifest.json
```

Final reports follow this structure:

- 摘要
- 核心 Findings / Experiments / Insights
- 逐页 PPT 解读 with image, time range, and grounded explanation
- QA, when evidence exists

The report writer is intentionally conservative: it should combine visible PPT content with ASR evidence, keep English technical terms in English, and write `不确定` when the evidence is insufficient. In Codex, Claude Code, Antigravity, and OpenClaw, the installed skill uses the host agent's own subagents for final writing; an OpenAI API key is only needed for pure CLI `--writer openai` mode or OpenAI ASR fallback.

## Quality Gates And Audit

`--writer agent` uses the host agent's LLM/VLM for cognition and writing, but the CLI still owns the gate checks. A report is not complete just because Markdown and JSON files exist. Final validation now includes a deterministic report-quality audit:

```bash
conference-report validate --out outputs/run --config outputs/run/config.yaml --phase report-quality
conference-report validate --out outputs/run --config outputs/run/config.yaml --phase final
```

The quality gate reads `reports_manifest.json`, `agent_slide_cognition_tasks.json`, `agent_qa_tasks.json`, `agent_report_tasks.json`, `agent_grounding_tasks.json`, the per-talk cognition/QA JSON, final Markdown reports, and grounding reviews. It writes `report_quality_validation.json` with per-report metrics and failure reasons.

The gate checks for template repetition, repeated boilerplate sentences, OCR/ASR copy-through, missing v2 slide cognition fields, missing `qa_pairs`, shallow QA fragments, missing claim-level `checked_claims`, missing report sections, broken image links, and whether findings appear to use slide cognition/QA outputs. If quality fails, `reports_manifest.final_reports` stays `false` and the CLI writes `agent_report_revision_tasks.json`. The run pauses at `report_revision`; the agent must rewrite only the failed reports and grounding reviews listed in each revision task's `allowed_write_paths`, then run `validate --phase final` and `resume` again.

This makes the audit trail explicit: evidence and intermediate cognition are preserved, report failures are machine-readable, and agent hosts follow validate → revise → resume rather than guessing the next step from chat context.

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
| torch + transformers + numpy | see `.[embeddings]` | local SigLIP/CLIP-family slide embeddings |
| tesseract | `>=5` recommended | local OCR evidence bundles |
| lxml | `>=5,<7` | faster HTML parsing |
| pytest | `>=8,<9` | tests |

Known-compatible pinned versions are listed in `requirements.lock`. Normal users should install from `pyproject.toml` or `requirements.txt`; the lock file is a reproducibility reference, not a strict requirement.

## Install

Clone and run the guided installer. For first-time users this is the recommended path: the installer explains each choice, checks the selected Python environment, and asks before installing optional components.

```bash
git clone https://github.com/houyili/conference-report-skill.git
cd conference-report-skill
python3 scripts/install.py
```

The guided flow can use a project `.venv` (recommended), the current Python environment, or conda when available. If using conda, create a new environment rather than installing into `base`. The installer checks whether `faster-whisper` is already installed before suggesting local ASR support, runs `pip check` after package installation, and can install the bundled skill into a user-selected global agent skills directory.

Installing the agent skill and making the CLI visible are separate steps. The skill tells an agent how to run the workflow, but the agent's shell still needs a usable `conference-report` command. At the end of the guided install, read the "Agent runtime check": it prints the absolute CLI path and warns if the current shell cannot resolve `conference-report` by name. The installer also records that absolute path in the installed skill copy at `.local/cli-path.txt` so agents that do not inherit your conda or shell `PATH` can still use the explicitly installed CLI. The `.local` directory is user-local install metadata and is not part of the repository source. You can also set `CONFERENCE_REPORT_CLI=/absolute/path/to/conference-report` for an agent runtime.

Command-line flags are available for automation and contributors. For example, `--with-dev` installs development dependencies such as `pytest` for running tests; it is not required for normal report generation.

On macOS, the installer can also guide you through Homebrew installation of `ffmpeg` and optional `tesseract`:

```bash
python3 scripts/install.py --with-local-asr --install-system-deps
```

`--install-system-deps` only installs system packages automatically on macOS when Homebrew is available. On Linux and Windows, the installer prints the recommended commands but does not run `apt`, `dnf`, `choco`, or `scoop` for you.

Manual install:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[asr,dev]"
brew install ffmpeg tesseract   # macOS example
```

For optional local semantic slide embeddings:

```bash
.venv/bin/python -m pip install -e ".[embeddings]"
```

Embeddings are an enhancement for dedupe candidate recall. If the extra is not installed, the CLI keeps conservative dedupe and writes a clear warning artifact instead of blocking the pipeline.

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

## Workspace And Outputs

There are two directories to keep in mind:

- **Install directory**: the cloned repository, for example `~/tools/conference-report-skill`. This contains `.venv`, `config.example.yaml`, scripts, and the source checkout.
- **Run workspace**: the directory passed to `--out`. Every pipeline artifact for one replay is written there.

For normal use through an installed agent skill, use the installed `conference-report` CLI. Do not rely on running `python -m conference_report.cli` from the checkout; that form is for contributor debugging and can hide PATH or upgrade problems in the globally installed skill.

If `--out` is relative, it is resolved from the shell's current working directory. Create a run-local config inside the run workspace so the run can be resumed, reviewed, or shared without referring back to the source checkout:

```bash
cd ~/reports/video-course
conference-report init-config outputs/session-demo/config.yaml --profile fast
conference-report build URL \
  --out outputs/session-demo \
  --config outputs/session-demo/config.yaml
```

This writes the run workspace to `~/reports/video-course/outputs/session-demo`. For reproducibility and easy cleanup, prefer one `--out` directory per replay/session.

## Update

For a source checkout installation:

```bash
cd conference-report-skill
git pull
.venv/bin/python -m pip install -e ".[asr]"
```

If you installed a global agent skill copy, refresh it after pulling:

```bash
python3 scripts/install_agent_skill.py upgrade
```

The upgrade command scans known local agent skill roots, recommends detected installed copies, and asks you to confirm. For automation or multiple agents, pass one or more explicit `--target-dir` values.

System dependencies update separately:

```bash
# macOS
brew upgrade ffmpeg tesseract

# Debian/Ubuntu
sudo apt-get update && sudo apt-get install --only-upgrade ffmpeg tesseract-ocr
```

Stored API keys remain in the OS credential store and do not need to be re-entered unless you want to rotate them.

## Uninstall

Run the guided uninstaller from the checkout. This is the recommended path for normal users because it detects the Python environment, installed global agent skill copies, optional ASR packages, and Homebrew `tesseract`, then asks before removing each item:

```bash
cd conference-report-skill
python3 scripts/uninstall.py
```

Safe defaults remove the `conference-report` Python package and detected global skill copies, while keeping shared packages such as `openai`, `keyring`, and `yt-dlp`, keeping stored OpenAI credentials unless you explicitly delete them, and never removing `ffmpeg` by default. Preview the flow without deleting anything:

```bash
python3 scripts/uninstall.py --dry-run
```

After the uninstaller finishes, remove the source checkout if you no longer want to keep it:

```bash
cd ..
rm -rf conference-report-skill
```

Generated outputs live wherever you passed `--out`; delete those run workspaces separately if you no longer need the raw audio, slides, transcripts, or reports.

Manual fallback, if the guided script is unavailable. Use the same Python environment you installed into:

```bash
conference-report auth delete openai
python3 -m pip uninstall conference-report faster-whisper
rm -rf /path/to/agent/skills/conference-report
```

Do not uninstall shared system tools unless you know no other local tools depend on them. If you do want to remove them:

```bash
# macOS
brew uninstall ffmpeg tesseract

# Debian/Ubuntu
sudo apt-get remove ffmpeg tesseract-ocr
```

## API Key And Privacy

For pure CLI OpenAI writing, store your own OpenAI API key in the OS credential store:

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

Page dumps created by `yt-dlp --write-pages` are renamed to neutral `page-0001.dump` style filenames after extraction. The tool also redacts token-like query parameters, signed URL fields, chat/user/session attributes, JWT-like strings, and AWS access-key-like strings from `raw/page.html` and `raw/page_dump/*.dump`.

For restricted conference pages, use browser cookies only when you are authorized to access the content:

```bash
RUN="outputs/iclr-session"
conference-report init-config "$RUN/config.yaml" --profile fast
conference-report build "https://iclr.cc/virtual/2026/session/..." \
  --out "$RUN" \
  --config "$RUN/config.yaml" \
  --cookies-from-browser chrome
```

The tool asks `yt-dlp` to read cookies from your local browser session. It does not bypass access controls and should not be used on content you are not allowed to access.

## Quick Start

```bash
RUN="outputs/run-name"
conference-report init-config "$RUN/config.yaml" --profile fast
conference-report build URL \
  --out "$RUN" \
  --config "$RUN/config.yaml" \
  --writer agent \
  --agent-gates dedupe,report
```

`--profile fast` skips optional audio preservation when platform subtitles are available, so smoke tests and normal agent-hosted runs avoid downloading large media files just for audit storage. If subtitles are missing, audio can still be downloaded for ASR fallback. Use `--profile full` or set `asr.save_audio: true` when you want preserved source audio and WAV artifacts.

With `--writer agent`, the CLI uses the host agent's LLM/VLM instead of requiring an OpenAI key for report writing. With `--agent-gates dedupe,report`, the CLI stops at agent review gates, writes `pipeline_state.json`, and prints the exact next command. Complete only the listed task manifests, then validate and resume:

```bash
conference-report status --out "$RUN"
conference-report validate --out "$RUN" --config "$RUN/config.yaml" --phase dedupe-review
conference-report resume --out "$RUN" --config "$RUN/config.yaml"
conference-report validate --out "$RUN" --config "$RUN/config.yaml" --phase final
conference-report resume --out "$RUN" --config "$RUN/config.yaml"
```

If a command is refused because a gate is waiting, do not skip ahead. Read `pipeline_state.json`, finish the current gate's outputs, validate, then resume.

Useful subcommands:

```bash
conference-report ingest URL --out outputs/run
conference-report asr URL --out outputs/run --config outputs/run/config.yaml
conference-report slides --out outputs/run --config outputs/run/config.yaml
conference-report dedupe --out outputs/run --config outputs/run/config.yaml
conference-report segment --out outputs/run --config outputs/run/config.yaml
conference-report report --out outputs/run --config outputs/run/config.yaml
conference-report status --out outputs/run
conference-report resume --out outputs/run --config outputs/run/config.yaml
conference-report validate --out outputs/run --config outputs/run/config.yaml --phase evidence
conference-report validate --out outputs/run --config outputs/run/config.yaml --phase dedupe-review
conference-report validate --out outputs/run --config outputs/run/config.yaml --phase agent-tasks
conference-report validate --out outputs/run --config outputs/run/config.yaml --phase final
```

Writer modes:

- `--writer agent`: prepare deterministic task manifests; the host skill executes only those JSON tasks, writes only `allowed_write_paths`, and uses `validate --phase final` plus `resume` as the completion gate. This is the default skill path and does not require an OpenAI API key.
- `--writer openai`: pure CLI automated writing with the user's own OpenAI API key.
- `--writer evidence`: write evidence bundles only.
- `--writer auto`: pure CLI default; use OpenAI when a key exists, otherwise evidence bundles.

If no writer backend is available, evidence bundles are useful for review, but they are not finished reports.

The `full` config profile keeps an audio audit artifact even when platform subtitles are available:

```yaml
asr:
  save_audio: true
  audio_required: false
embeddings:
  enabled: true
  provider: local_siglip
  model: google/siglip-base-patch16-224
  device: auto
  cache_dir: embeddings
```

The `fast` profile writes the same structure with `save_audio: false`. You can also edit the run-local config manually. Set `audio_required: true` when a run should fail if audio preservation is impossible.

## Manual Segments

If the conference page does not expose a schedule, the pipeline writes `segmentation/manual_segments.template.yaml`. You can also provide your own:

```bash
conference-report segment \
  --out outputs/run \
  --config outputs/run/config.yaml \
  --manual-segments examples/manual_segments/manual_segments.template.yaml
```

Breaks such as coffee, poster sessions, lunch, and registration are retained in segmentation review artifacts but do not generate reports.

## Agent Skill Install

To install the bundled skill into an agent host such as Codex, Claude Code, Antigravity, OpenClaw, or another skill-compatible tool, run the guided installer. It scans known local agent roots and asks you to confirm or type a path:

```bash
python3 scripts/install_agent_skill.py install
```

For non-interactive automation or multiple agent hosts, repeat `--target-dir`:

```bash
python3 scripts/install_agent_skill.py install \
  --target-dir /path/to/first-agent/skills \
  --target-dir /path/to/second-agent/skills
```

After changing the source checkout, use `upgrade` instead of `install`:

```bash
python3 scripts/install_agent_skill.py upgrade
```

You can also use `python3 scripts/install_agent_skill.py upgrade -` to force the same interactive target selection. The legacy `scripts/install_codex_skill.py` wrapper is still available for Codex users, but it requires `--target-dir`; the primary cross-agent installer is preferred for guided install and upgrade.

The skill is intentionally small. User-facing setup and dependency information lives in this README; the skill itself tells agents how to run the pipeline, execute task manifests in order, obey `allowed_write_paths`, and preserve report quality.

## Development

Run tests:

```bash
.venv/bin/python -m pytest
```

Validate the bundled skill if you have a compatible skill validator script:

```bash
python3 /path/to/quick_validate.py skills/conference-report
```

You can also install the repository pre-push hook. It runs the local test suite before push and can run a validator when `CONFERENCE_REPORT_SKILL_VALIDATOR` points to one:

```bash
python3 scripts/install_git_hooks.py
```

## Current Scope

This is a v1 alpha. It is intentionally conservative:

- SlidesLive-style slide metadata is preferred when available.
- Otherwise, `ffmpeg` scene/interval screenshots are used. For ordinary videos that miss slide changes, set `slides.video_mode: interval` and tune `slides.interval_seconds` in the config.
- Slide dedupe preserves provenance and never deletes `slides_original/`.
- Optional local semantic embeddings recall similar slide pairs under brightness, scale, camera, or perspective changes; agent/VLM review tasks are audit artifacts, while CLI validation remains the workflow gate.
- Schedule parsing is best-effort and currently strongest for ICLR-style pages.
- Report writing uses host-agent task execution in skill mode, OpenAI Responses API only when `--writer openai` is configured, or evidence bundles when requested/no key is available.

Contributions that improve schedule parsers, video backends, and non-OpenAI writer adapters are welcome.
