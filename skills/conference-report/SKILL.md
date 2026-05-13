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

Then create a run-local config and start the pipeline. For `--writer agent`, ask for subagent authorization before build/report gate when the host framework requires explicit permission to spawn workers. Explain that final `report_write` needs one clean report-writing subagent per report: one subagent per report, not one parent-context writer for all reports. Without that authorization the run can still produce evidence and stop at `report_agent`, but it cannot complete agent-written final reports.

```bash
RUN="outputs/<run-name>"
"$CLI" init-config "$RUN/config.yaml" --profile fast
"$CLI" build "$URL" \
  --out "$RUN" \
  --config "$RUN/config.yaml" \
  --writer agent \
  --agent-gates dedupe,report \
  --cookies-from-browser chrome
```

The recommended `--profile fast` skips optional audio preservation when platform subtitles are available, which makes user acceptance tests and ordinary agent runs much faster. If subtitles are missing, the CLI can still download audio for ASR fallback. Use `--profile full` or edit `asr.save_audio: true` in the run-local config when the user wants preserved audio/WAV audit artifacts. If `build` is run without `--config`, the CLI writes `run-config.yaml` inside the output directory and uses that file for resume commands.

Agent-hosted use does not require an OpenAI API key. The CLI prepares evidence plus deterministic JSON task manifests; the host agent only executes the current gate's tasks and writes the exact files named in each task's `allowed_write_paths`.

Developer-only source checkout debugging may use the package module form, but this is not a use-stage path:

```bash
python -m conference_report.cli build "$URL" \
  --out "$RUN" \
  --config "$RUN/config.yaml"
```

Use `--writer openai` only for pure CLI writing with the user's own `OPENAI_API_KEY` or credential store. Use `--writer evidence` or legacy `--dry-run-report` only when the user explicitly wants evidence bundles instead of final reports.

## Agent Gates

Agent 不决定下一步。The CLI is the workflow controller: it runs deterministic Python stages until an agent/VLM gate is reached, writes `pipeline_state.json`, prints the next command, then stops. Do not guess the next stage from context.

When a run is paused, inspect the state:

```bash
"$CLI" status --out outputs/<run-name>
```

The equivalent literal commands are `conference-report status --out outputs/<run-name>` and `conference-report resume --out outputs/<run-name> --config outputs/<run-name>/config.yaml` when `conference-report` is visible on `PATH`.

Only execute the task manifests named in `pipeline_state.json`. After writing every task output, validate the current gate, then resume:

```bash
"$CLI" validate --out "$RUN" --config "$RUN/config.yaml" --phase dedupe-review
"$CLI" resume --out "$RUN" --config "$RUN/config.yaml"
```

For report writing, final validation is the gate check:

```bash
"$CLI" validate --out "$RUN" --config "$RUN/config.yaml" --phase report-quality
"$CLI" validate --out "$RUN" --config "$RUN/config.yaml" --phase final
"$CLI" resume --out "$RUN" --config "$RUN/config.yaml"
```

`--phase final` includes `--phase report-quality` for `--writer agent` runs. The separate `report-quality` phase is useful when auditing an existing run before attempting `resume`.

If the CLI refuses a command because the run is blocked, 不要猜下一步. Read `pipeline_state.json`, complete the listed task manifests, run the printed `validate` command, then run the printed `resume` command.

## Agent-Native Writing

When the CLI stops at the `report_agent` gate, first validate the generated task contracts if the state output asks for it:

```bash
"$CLI" validate --out "$RUN" --config "$RUN/config.yaml" --phase agent-tasks
```

Then read the task manifests from the run directory:

- `agent_slide_cognition_tasks.json`
- `agent_qa_tasks.json`
- `agent_report_dispatch_plan.json`
- `agent_report_tasks.json`
- `agent_grounding_tasks.json`

The agent host does not decide the workflow. Execute tasks in this order: `slide_cognition`, `qa_detection`, dependency validation, `report_write`, then `grounding_review`, then `report-quality` validation, then revision if needed. Read `agent_report_dispatch_plan.json` before `report_write`: it maps each report task to exactly one clean report-writing subagent and records `dependency_validation_phase`, expected dependency counts, and ready/not-ready status. Do not dispatch a report writer until its declared slide cognition and QA dependency outputs exist and the current agent-tasks validation passes. Re-run `validate --phase agent-tasks` after writing slide cognition and QA outputs; this phase validates any existing dependency JSON and refreshes `agent_report_dispatch_plan.json` plus `agent_dependency_status.json` with current readiness. If a worker item still has `dependencies_ready: false`, do not start that report writer.

If the host supports subagents but requires explicit user approval, ask before dispatching them. At this gate, slide cognition, QA detection, and grounding review may be completed sequentially in the parent context when needed, but report_write cannot be completed sequentially in parent context. Final report writing must produce `worker_type: subagent` provenance, so a parent-written report will fail `validate --phase final`. If the host has no subagent capability or the user does not authorize it, stop at the gate or switch to `--writer evidence` / `--writer openai`; do not pretend the output is an agent-written final report. Do not skip a stage and do not edit any task manifest.

Every task is self-contained. Give the worker only the JSON task object and its listed files:

- `task_id` and `stage`: identity and workflow stage
- `input_paths`: existing files/directories to read
- `dependency_output_paths`: prior task outputs that must already exist before this task runs
- `intermediate_output_paths`: required intermediate artifacts such as `talk_synthesis.md`
- `output_paths`: files this task must produce
- `allowed_write_paths`: the only paths this task may create or replace
- `required_sections`, `required_schema`, and `validation_rules`: completion criteria
- `execution_provenance_path` and `required_provenance` for report-writing tasks: proof that the final report was written by an isolated subagent

Workers must not edit shared manifests, source files, credentials, cookies, unrelated outputs, or any path not listed in `allowed_write_paths`. Report-writing tasks must write final Markdown reports with the required report structure below.

Use absolute paths exactly as written in the manifests. Do not reconstruct paths from a run name, slug, previous test directory, current shell directory, or memory of an earlier run. When batching several non-report dependency tasks for convenience, the batch prompt must still be a pure union of those exact task objects, `input_paths`, `dependency_output_paths`, and `allowed_write_paths`; never give a worker a broad output root or an old relative `outputs/...` path.

Agent 的目标是 report quality，不是填完文件。不要把 OCR/ASR 机械填进报告，也不要用脚本批量生成浅层 JSON 来伪装已经理解了 talk。

For final report writing, one `agent_report_tasks.json` item equals one dedicated report-writing subagent when the host supports subagents: one clean subagent context per report, not one shared writer across talks. That worker must build topic-level understanding before writing: read the metadata, full ASR transcript or timeline, preserved slide screenshots, OCR evidence, slide cognition outputs, QA outputs, and any synthesis manifests for that assigned topic. The worker first writes `talk_synthesis.md` to the task's `synthesis_path`, summarizing the research problem, method, experiment/result chain, limitations, Q&A boundary, slide role map, evidence-only slides, and uncertainties. Only after that should it write the opening overview and per-slide explanations. OCR, ASR, and screenshots are evidence for understanding, not report prose; keep slide screenshots available, but do not turn noisy OCR tokens into concepts or force low-information slides into generic explanations.

The parent agent's report dispatch job is narrow: read `agent_report_dispatch_plan.json`, create one worker per listed report task, pass only that task object plus its `input_paths` and `dependency_output_paths`, wait for the Markdown report and provenance JSON, then run validation and resume. The parent agent may coordinate workers, but it must not write the final report itself.

Report-writing tasks must also write `report_writer_provenance.json` to the task's `execution_provenance_path`. This is a hard final gate, not optional metadata. The JSON must include `worker_type: subagent`, `isolation_scope: single_report`, `host_agent_framework`, `worker_id`, `assigned_task_id`, `assigned_slug`, `topic_understanding_confirmed: true`, `input_paths_read`, `output_paths_written`, and `allowed_write_paths`. `output_paths_written` must include the final Markdown report, `talk_synthesis.md`, and the provenance JSON when the task declares those paths. If a later `report_revision` task rewrites the report, keep provenance assigned to the original `report:<slug>` task named by `original_report_task_id` / `provenance_assignment`; do not replace it with `report-revision:<slug>`. If `validate --phase final` cannot verify this provenance, the run is not complete.

Quality expectations by stage:

- `slide_cognition`: if the host has VLM/image understanding, inspect the slide image. Write `visual_summary`, `speaker_intent`, `main_claims`, `method_details`, `experiment_or_result`, `numbers_and_entities`, `asr_corrections`, `uncertainties`, and `confidence`. If there is no VLM, rely on OCR/ASR conservatively and put the limitation in `uncertainties`.
- `qa_detection`: write `qa_pairs`, not transcript fragments. Each pair needs `question`, `answer`, `time_range`, `evidence_quotes`, and `confidence`. If no reliable pair exists, leave `qa_pairs` empty and explain why.
- `report_write`: read all slide cognition and QA outputs first, write `talk_synthesis.md`, then write the final report from that whole-talk understanding. Synthesize claims and evidence; do not repeat the same page template or expose `evidence.json` row numbers, original `slide_index` bookkeeping, or standalone `slide_index:` lines in reader-facing prose.
- `grounding_review`: review the report claim by claim and as reader-facing prose. `checked_claims` must be non-empty for substantive reports; set `template_or_style_issues` and `requires_revision: true` for unsupported claims, missing slide coverage, template prose, visible audit scaffolding, over-expanded low-information slides, or QA misuse.

After each stage, the parent agent may rerun the task validation phase. After all stages finish, final validation and resume are mandatory:

```bash
"$CLI" validate --out "$RUN" --config "$RUN/config.yaml" --phase agent-tasks
"$CLI" validate --out "$RUN" --config "$RUN/config.yaml" --phase report-quality
"$CLI" validate --out "$RUN" --config "$RUN/config.yaml" --phase final
"$CLI" resume --out "$RUN" --config "$RUN/config.yaml"
```

If `--phase final` fails quality checks, the CLI writes `report_quality_validation.json`, creates `agent_quality_repair_plan.json`, and blocks at the `report_quality_repair` gate. Follow validate → revise → resume: read the repair plan, complete the listed manifests in this exact order, rerun `validate --phase final`, then run `resume`.

```text
slide_cognition_revision -> qa_revision -> report_revision -> grounding_revision
```

Repair manifests may include:

- `agent_slide_cognition_revision_tasks.json`: rewrite failed `slide_cognition/*.json` files with v2 semantic fields.
- `agent_qa_revision_tasks.json`: write canonical `qa/qa_pairs.json`; old `qa_candidates.json` fragments are not enough.
- `agent_report_revision_tasks.json`: rewrite only failed Markdown reports after cognition and QA are fixed.
- `agent_grounding_revision_tasks.json`: rewrite claim-level grounding reviews after reports are fixed.

Do not only rewrite the report if `agent_quality_repair_plan.json` lists upstream cognition or QA revision tasks. Old completed runs can also be audited with `validate --phase final`; if quality fails, the CLI will write the same repair plan and move `pipeline_state.json` back to a waiting `report_quality_repair` gate.

If `--phase final` fails for any reason, do not claim final reports are complete. Read `validation.json`, `agent_task_validation.json`, and `report_quality_validation.json` when present; fix only the failed task outputs permitted by `allowed_write_paths`, and rerun final validation. When report-quality later passes, an old `agent_quality_repair_plan.json` may be marked `resolved` or `superseded_by` instead of being deleted.

## Pipeline

Run stages in order when debugging:

1. `ingest`: save metadata, subtitles, and authorized page dumps with `yt-dlp`.
2. `asr`: prefer platform subtitles; preserve audio/WAV when `asr.save_audio` is enabled; fall back to local `faster-whisper` or OpenAI transcription if configured.
3. `slides`: prefer slide metadata; otherwise extract screenshots from video.
4. `dedupe`: preserve originals, cluster repeated slides, record `main_interval` plus `all_intervals`, and optionally stop at a `dedupe-review` gate with local semantic embedding candidates for agent/VLM review.
5. `segment`: parse the schedule first, align actual talk starts to transcript cues, and skip coffee/poster/lunch/break segments.
6. `report`: create per-talk evidence and agent writing tasks, or write reports with an explicit writer backend.
7. `validate`: run `evidence`, `agent-tasks`, `report-quality`, or `final` phase checks. Final validation checks task outputs, required report sections, JSON schemas, Markdown image links, report-quality metrics, QA pairs, and claim-level grounding review.

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
- `talks/<talk_slug>/qa/qa_pairs.json`: persistent QA pair detection output
- `talks/<talk_slug>/talk_synthesis.md`: report-writer synthesis of the whole talk before final drafting
- `talks/<talk_slug>/agent_execution/report_writer_provenance.json`: required proof that the report was written by one isolated subagent
- `talks/<talk_slug>/report_writer_prompt.md`: writer instructions
- `agent_slide_cognition_tasks.json`: one bounded cognition task per evidence slide when `--writer agent` is used
- `agent_qa_tasks.json`: one bounded QA detection task per reportable talk/topic
- `agent_report_dispatch_plan.json`: one worker item per final report-writing subagent, plus authorization, dependency readiness, and fallback guidance
- `agent_dependency_status.json`: refreshed readiness summary after `validate --phase agent-tasks`, including missing or invalid report-writing dependencies
- `agent_report_tasks.json`: one bounded report-writing task per reportable talk/topic
- `agent_grounding_tasks.json`: one bounded grounding review task per final report
- `agent_task_validation.json`: machine-readable status for task contract or final-output validation
- `report_quality_validation.json`: quality audit for agent-written reports
- `agent_quality_repair_plan.json`: ordered repair plan created when report quality fails
- `agent_slide_cognition_revision_tasks.json`: bounded cognition repair tasks
- `agent_qa_revision_tasks.json`: bounded QA pair repair tasks
- `agent_report_revision_tasks.json`: bounded report rewrite tasks
- `agent_grounding_revision_tasks.json`: bounded grounding review repair tasks
- `pipeline_state.json`: current gate, task manifests, next validation command, and resume command when a run is paused
- `reports/<talk_slug>.md`: final report written by subagents/OpenAI, or clearly marked evidence bundle
- `reports/<talk_slug>.grounding.json`: persistent grounding review for the final report

## Report Rules

- A final report must cover exactly one talk/keynote/panel.
- Required sections: `摘要`, `核心 Findings / Experiments / Insights`, `逐页 PPT 解读`, and `QA`.
- Each slide section must preserve image Markdown and time range, then explain the slide by combining visible PPT content with the matching ASR window.
- Write Chinese explanatory prose while preserving English technical terms.
- Stay grounded. If PPT, ASR, or OCR is ambiguous, write `不确定` or `ASR 可能错误`; do not add external paper knowledge.
- Do not produce template prose. Repeated sentences, OCR/ASR copying, reader-visible audit scaffolding, fragment QA, or empty grounding review should fail `validate --phase report-quality`.
- Do not put audit language in the report body: avoid phrases such as `证据源为 evidence.json`, `原始 PPT slide_index`, `evidence 记录`, or standalone `slide_index:` metadata lines. Keep these identities in grounding/provenance/synthesis artifacts instead.
- Keep `local_evidence_index`, `original_slide_index`, and `report_section_number` conceptually separate. Coverage validation accepts common headings such as `第 N 张` and `Slide N`, but the reader-facing prose does not need to display every bookkeeping identity.
- Skip low-information conference logo, blank, chair-transition, cross-talk transition, repeated Q&A navigation, and generic cover pages unless they contain substantive talk-specific content. Keep them traceable as skipped or evidence-only material instead of forcing a full main-body explanation.
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
