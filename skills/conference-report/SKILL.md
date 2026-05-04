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
  --writer agent \
  --agent-gates dedupe,report \
  --cookies-from-browser chrome
```

Agent-hosted use does not require an OpenAI API key. The CLI prepares evidence plus deterministic JSON task manifests; the host agent only executes the current gate's tasks and writes the exact files named in each task's `allowed_write_paths`.

Developer-only source checkout debugging may use the package module form, but this is not a use-stage path:

```bash
python -m conference_report.cli build "$URL" \
  --out outputs/<run-name> \
  --config config.example.yaml
```

Use `--writer openai` only for pure CLI writing with the user's own `OPENAI_API_KEY` or credential store. Use `--writer evidence` or legacy `--dry-run-report` only when the user explicitly wants evidence bundles instead of final reports.

## Agent Gates

Agent 不决定下一步。The CLI is the workflow controller: it runs deterministic Python stages until an agent/VLM gate is reached, writes `pipeline_state.json`, prints the next command, then stops. Do not guess the next stage from context.

When a run is paused, inspect the state:

```bash
"$CLI" status --out outputs/<run-name>
```

The equivalent literal commands are `conference-report status --out outputs/<run-name>` and `conference-report resume --out outputs/<run-name> --config config.example.yaml` when `conference-report` is visible on `PATH`.

Only execute the task manifests named in `pipeline_state.json`. After writing every task output, validate the current gate, then resume:

```bash
"$CLI" validate --out outputs/<run-name> --config config.example.yaml --phase dedupe-review
"$CLI" resume --out outputs/<run-name> --config config.example.yaml
```

For report writing, final validation is the gate check:

```bash
"$CLI" validate --out outputs/<run-name> --config config.example.yaml --phase final
"$CLI" resume --out outputs/<run-name> --config config.example.yaml
```

If the CLI refuses a command because the run is blocked, 不要猜下一步. Read `pipeline_state.json`, complete the listed task manifests, run the printed `validate` command, then run the printed `resume` command.

## Agent-Native Writing

When the CLI stops at the `report_agent` gate, first validate the generated task contracts if the state output asks for it:

```bash
"$CLI" validate --out outputs/<run-name> --config config.example.yaml --phase agent-tasks
```

Then read the task manifests from the run directory:

- `agent_slide_cognition_tasks.json`
- `agent_qa_tasks.json`
- `agent_report_tasks.json`
- `agent_grounding_tasks.json`

The agent host does not decide the workflow. Execute tasks in this order: `slide_cognition`, `qa_detection`, `report_write`, then `grounding_review`. If the host supports subagents, create one subagent per task within the current stage. If the host has no subagent support, execute the tasks sequentially in the same stage order. Do not skip a stage and do not edit any task manifest.

Every task is self-contained. Give the worker only the JSON task object and its listed files:

- `task_id` and `stage`: identity and workflow stage
- `input_paths`: existing files/directories to read
- `dependency_output_paths`: prior task outputs that must already exist before this task runs
- `output_paths`: files this task must produce
- `allowed_write_paths`: the only paths this task may create or replace
- `required_sections`, `required_schema`, and `validation_rules`: completion criteria

Workers must not edit shared manifests, source files, credentials, cookies, unrelated outputs, or any path not listed in `allowed_write_paths`. Report-writing tasks must write final Markdown reports with the required report structure below.

After each stage, the parent agent may rerun the task validation phase. After all stages finish, final validation and resume are mandatory:

```bash
"$CLI" validate --out outputs/<run-name> --config config.example.yaml --phase agent-tasks
"$CLI" validate --out outputs/<run-name> --config config.example.yaml --phase final
"$CLI" resume --out outputs/<run-name> --config config.example.yaml
```

If `--phase final` fails, do not claim final reports are complete. Read `validation.json` and `agent_task_validation.json`, fix only the failed task outputs permitted by `allowed_write_paths`, and rerun final validation.

## Pipeline

Run stages in order when debugging:

1. `ingest`: save metadata, subtitles, and authorized page dumps with `yt-dlp`.
2. `asr`: prefer platform subtitles; preserve audio/WAV when `asr.save_audio` is enabled; fall back to local `faster-whisper` or OpenAI transcription if configured.
3. `slides`: prefer slide metadata; otherwise extract screenshots from video.
4. `dedupe`: preserve originals, cluster repeated slides, record `main_interval` plus `all_intervals`, and optionally stop at a `dedupe-review` gate with local semantic embedding candidates for agent/VLM review.
5. `segment`: parse the schedule first, align actual talk starts to transcript cues, and skip coffee/poster/lunch/break segments.
6. `report`: create per-talk evidence and agent writing tasks, or write reports with an explicit writer backend.
7. `validate`: run `evidence`, `agent-tasks`, or `final` phase checks. Final validation checks task outputs, required report sections, JSON schemas, and Markdown image links.

## Output Contract

Each run directory should contain:

- `asr/timeline.txt`: `[HH:MM:SS.mmm] text`
- `raw/audio/` and `asr/audio/`: preserved source audio/media and 16 kHz WAV when `asr.save_audio: true`
- `slides_original/`: original screenshots, never deleted during dedupe
- `slides_dedup/`: representative slide PNGs
- `embeddings/slides/`: optional local SigLIP/CLIP-family semantic embedding cache
- `dedupe/semantic_candidates.json`: embedding-recalled possible same-slide pairs needing review
- `dedupe/agent_review_tasks.json`: optional bounded review tasks for uncertain semantic dedupe candidates
- `dedup_groups.json`: visual slide clusters with provenance and repeated intervals
- `slide_intervals.json/csv`: chronological slide intervals
- `segmentation/talks.json`: talk/keynote/panel boundaries and confidence
- `segmentation/review.html`: segmentation review
- `talks/<talk_slug>/`: one material bundle per reportable talk
- `talks/<talk_slug>/evidence.json`: OCR plus ASR evidence per reportable slide
- `talks/<talk_slug>/slide_cognition/*.json`: persistent agent/VLM cognition for each slide task
- `talks/<talk_slug>/qa/qa_candidates.json`: persistent QA detection output
- `talks/<talk_slug>/report_writer_prompt.md`: writer instructions
- `agent_slide_cognition_tasks.json`: one bounded cognition task per evidence slide when `--writer agent` is used
- `agent_qa_tasks.json`: one bounded QA detection task per reportable talk/topic
- `agent_report_tasks.json`: one bounded report-writing task per reportable talk/topic
- `agent_grounding_tasks.json`: one bounded grounding review task per final report
- `agent_task_validation.json`: machine-readable status for task contract or final-output validation
- `pipeline_state.json`: current gate, task manifests, next validation command, and resume command when a run is paused
- `reports/<talk_slug>.md`: final report written by subagents/OpenAI, or clearly marked evidence bundle
- `reports/<talk_slug>.grounding.json`: persistent grounding review for the final report

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

For pure CLI OpenAI writing, use the CLI credential store:

```bash
conference-report auth set openai
conference-report auth status openai
```

The CLI checks `OPENAI_API_KEY` first, then the OS credential store. Codex, Claude Code, Antigravity, and OpenClaw skill usage should prefer `--writer agent` and host subagents instead of requiring an OpenAI API key.
