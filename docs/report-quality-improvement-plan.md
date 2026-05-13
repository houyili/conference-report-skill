# Installed Skill E2E Test Review And Report Quality Improvement Plan

## Summary

This design note reviews the installed `conference-report` skill end-to-end acceptance test for `session-10012011-installed-skill-test` and proposes report-quality improvements.

The run proved that the installed-skill workflow can complete a gated, agent-native conference-report pipeline: authenticated ingest, subtitle-based ASR, slide metadata extraction, dedupe, segmentation, slide cognition, QA detection, isolated report-writing subagents, grounding review, repair, and final validation all reached a completed state.

The remaining product gap is not pipeline completion. It is report reading quality. The generated reports are grounded and structurally complete, but the per-slide prose can read like validation evidence rather than like a writer who has understood the whole talk and is explaining how each slide advances the work.

## What Worked As Expected

- The run used the installed skill and installed CLI path, not the source checkout or `python -m conference_report.cli`.
- The authenticated ICLR page was accessible once browser login state was explicitly authorized.
- The `fast` profile behaved as intended: the run used platform metadata and subtitles instead of forcing preserved media/audio artifacts.
- The pipeline reached all major stages: ingest, ASR, slides, dedupe, segment, report, validate, report-quality repair, and final completion.
- The agent-native report gate worked as designed. The run produced 109 slide cognition outputs, 4 QA outputs, 4 final reports, 4 grounding reviews, and report-writing provenance for one isolated subagent per report.
- Final validation passed with no reported errors or warnings.
- The report-quality repair gate was useful. It caught slide coverage, QA usage, and missing grounding issues, then allowed the run to pass after targeted repair.

## What Did Not Work As Expected

- Final validation passed even though the reports still felt too mechanical to a human reviewer.
- Report prose exposed audit scaffolding such as `evidence.json`, source row numbers, and repeated `slide_index` references in the reader-facing body.
- Slide coverage validation was too format-sensitive. It recognized Chinese headings such as `第 N 张`, but initially did not recognize equivalent forms such as `Slide N` or `slide_index: N`.
- Low-information pages, repeated Q&A navigation pages, and chair/logistics material could still enter the main per-slide report body instead of being handled as appendix or evidence-only material.
- Grounding review focused on claim support, but did not flag prose quality issues such as repetitive structure, validation-oriented wording, or visible evidence scaffolding.
- After final success, the historical repair plan could still contain `blocked_gate: report_quality_repair` with zero remaining tasks. That is technically historical state, but confusing for a user reading artifacts after completion.

## Sampled Intermediate Artifact Audit

After the initial design pass, a focused audit sampled 20 slide sections across the 4 reports and compared each sample against `evidence.json`, `slide_cognition/*.json`, the final report section, the grounding JSON, and selected slide screenshots. The audit inspected representative transition, motivation, method, result, Q&A, and repeated-slide cases.

The key finding is that the reports are mostly grounded at the claim level, but the artifacts expose several orchestration and quality-gate weaknesses:

- **Slide cognition is often useful, but not fully exploited.** Sampled cognition files frequently contain good speaker-intent summaries and claim lists. For example, the MoE 2B activation-rate slide correctly captures that fixed-`r_a` data scaling and fixed-`D` activation scaling behave differently. The final report repeats this correctly, but still starts from evidence bookkeeping rather than a talk-level synthesis.
- **Reader-facing reports leak audit metadata.** A marker count across final Markdown reports found many visible audit markers: talk-001 had 41 matches, talk-002 had 22, talk-003 had 92, and talk-004 had 45 for patterns such as `slide_index:`, `证据源为 evidence.json`, and `evidence 记录`.
- **Grounding review misses style failures.** All 4 grounding files had `template_or_style_issues: []` and `requires_revision: false`, even when sampled sections visibly repeated `slide_index:` lines or exposed `evidence.json` references in the main prose.
- **Local slide order and original PPT identity are mixed.** Some talks have non-contiguous original slide numbers. For example, talk-002's first evidence row has `evidence.slide_index = 2`, while the report labels it `Slide 1`; talk-003 has 46 evidence rows but reaches original `slide_index = 48`; talk-004 has 15 evidence rows but reaches original `slide_index = 17`. This is valid data, but the report currently blurs local report order, evidence row identity, and original PPT slide identity.
- **Transition and cross-talk slides need better handling.** Talk-003's first report slide is visually the previous talk's LLM DNA conclusion slide while the audio has moved to the Hubble introduction. The report recognizes this, but it still appears as a main slide section. This should become evidence-only or appendix material.
- **Repeated Q&A slides are over-represented in the main narrative.** Several sampled Q&A sections reuse earlier slides as visual context. The report often explains that they are repeats, but the main body still expands them page by page instead of consolidating them under Q&A or appendix evidence.

This audit turns the earlier product judgment into an evidence-backed conclusion: the current pipeline is not hallucinating wholesale, but it is overfitting final prose to validation scaffolding and lacks a persisted whole-talk synthesis layer.

## Why The Reports Became Mechanical

The current workflow strongly optimizes for verifiability, and that pressure leaks into the prose.

The report-writing prompt tells the subagent to explain every slide by combining visible PPT content with the matching transcript window. That is a good grounding rule, but it does not force the writer to first build a talk-level argument map: research problem, method, experimental progression, results, limitations, and speaker intent. Without that explicit synthesis step, the writer can produce a sequence of locally correct page explanations that do not feel like a coherent reading of the whole work.

The validator mostly checks structure and evidence mechanics: required sections, image links, slide coverage, OCR/ASR copying, stock phrases, use of slide cognition, QA usage, grounding JSON, and provenance. Those checks are necessary, but they do not detect whether a slide explanation says how the slide advances the paper's argument.

The subagent also has an incentive to make support visible by writing phrases like `evidence.json 第 N 条` directly in the report. That improves auditability for a validator, but it makes the final report read like an execution log. Evidence anchors should remain available through grounding JSON, provenance, footnotes, or appendix metadata; they should not dominate the main explanatory prose.

## System-Orchestration Improvement Angles

### Subagent Prompts And Dispatch Timing

The current split between parent orchestration and isolated report-writing subagents is directionally correct. The weakness is that the report writer is dispatched after slide cognition and QA exist, but the task contract does not require a visible whole-talk synthesis before drafting. The subagent therefore has all evidence but no required planning checkpoint.

Improve this by making report writing a two-step subagent task:

1. Read all assigned evidence and write a private or persisted talk-level synthesis: thesis, method, experiment flow, result ladder, limitations, slide roles, and Q&A boundaries.
2. Draft the final report from that synthesis, using slide-level evidence to support the narrative rather than to drive the structure mechanically.

The dispatch plan should continue to require exactly one clean report-writing subagent per report. Slide cognition, QA detection, and grounding review may remain parent-or-parallel tasks, but final report writing should not start until every declared dependency output for the assigned report exists and validates.

### Hard Orchestration

The hard gate design is mostly reasonable: the CLI, not the parent agent, controls stage order; the parent agent executes only manifests named in `pipeline_state.json`; report writers can only write `allowed_write_paths`; final validation checks provenance.

The improvement is to make the hard orchestration more explicit about quality prerequisites, not looser. The pipeline should not allow report writing to begin merely because files exist. It should require that slide cognition and QA outputs pass schema and semantic-depth checks first. Likewise, report-quality repair should follow the same hard order: cognition/QA repair before report repair, report repair before grounding repair.

This keeps the system agent-native without becoming parent-agent improvisation. The parent coordinates, but the manifests decide.

### Feedback And Iterative Improvement Loop

The current feedback loop works only after validation failure. It can repair missing coverage, missing QA use, and missing grounding, but it has weak feedback for style and understanding quality.

Improve the loop by making feedback artifacts more specific and actionable:

- `report_quality_validation.json` should distinguish support failures, coverage failures, style failures, evidence-scaffolding failures, and synthesis failures.
- `agent_quality_repair_plan.json` should explain which upstream artifact caused the failure and which task must be re-run.
- Grounding review should give claim-level support feedback and prose-level feedback, not just `requires_revision`.
- Repair prompts should include the failed excerpts or issue summaries so the revision subagent does not have to infer the defect from a generic validation error.

The intended loop is: produce evidence, validate evidence quality, write report, review grounding and prose, repair the narrow failed artifact, then revalidate. Feedback should be an artifact that future agents can read, not just a terminal message.

### Intermediate Artifact Persistence

The run already persists the right broad categories: metadata, ASR timeline, slide intervals, evidence rows, slide cognition JSON, QA pairs, report tasks, provenance, grounding reviews, validation output, and repair plans.

The sampled audit confirms that the missing persisted artifact is the talk-level synthesis that bridges slide-level cognition and report prose. Add one of these:

- `talk_synthesis.md` for human-readable narrative planning.
- `argument_map.json` for structured downstream validation.

For a first implementation, `talk_synthesis.md` is enough. It should live under each `talks/<slug>/` directory and be listed as a dependency for `report_write`. It should not contain private credentials or raw transcript dumps. It should summarize what the worker understood: the core question, method, result chain, slide-role map, Q&A takeaways, uncertainty notes, and which slides are evidence-only.

This makes understanding auditable without forcing audit scaffolding into the final report.

## Improvement Priorities

### P0: Improve The Writer Contract

Update the report writer prompt and report task quality contract so the writer must first build a talk-level understanding before writing per-slide explanations.

The writer should explicitly connect each substantive slide to one of the talk's roles: motivation, formal setup, method, experimental design, result, ablation, limitation, conclusion, or Q&A clarification. Reader-facing prose should not include raw audit phrases such as `evidence.json 第 N 条`, `原始 PPT slide_index`, or repeated standalone `slide_index:` lines.

### P0: Make Slide Coverage Format-Tolerant

Update slide coverage parsing so the validator accepts common equivalent formats:

- Chinese headings such as `第 7 张`
- English headings such as `Slide 7`
- Metadata lines such as `slide_index: 7`

Coverage should be validated against evidence identity, not against one required heading style.

Also separate three identities in task manifests and reports:

- `local_evidence_index`: the 1-based row number inside the talk evidence bundle.
- `original_slide_index`: the slide number from the replay or PPT metadata when available.
- `report_section_number`: the reader-facing order in the report.

The main prose should not need to show all three. The grounding JSON and traceability metadata should preserve them.

### P0: Gate Report Dispatch On Validated Dependencies

Before dispatching report-writing subagents, validate that the assigned slide cognition and QA outputs exist and pass the current task-quality checks. Do not treat raw existence as sufficient readiness.

The dispatch plan should make this visible by listing `dependency_validation_phase`, expected dependency counts, and a ready/not-ready status for each report worker item.

### P1: Separate Main Report Slides From Evidence-Only Slides

Distinguish substantive reportable slides from low-information, repeated, or navigation-only evidence slides.

The main report should focus on slides that carry talk content. Low-information conference branding, chair logistics, blank screens, repeated Q&A navigation pages, and pure transition pages should remain traceable, but should move to appendix, skipped-slide metadata, or evidence-only coverage instead of forcing a full prose section in the main body.

The sampled audit shows this is not theoretical: the Hubble report includes a previous-talk conclusion slide as its first main section, and Train-before-Test includes repeated Q&A navigation slides that should be consolidated.

### P1: Add Style-Quality Validation

Add report-quality checks for reader-facing prose problems that current validators miss:

- visible audit scaffolding in the main report body
- repeated `slide_index:` metadata lines
- repeated paragraph openings such as `这一页...` or `证据源为...`
- page-by-page text that follows the same rigid two-paragraph pattern
- grounding reviews that omit style concerns when the report is visibly validation-oriented

### P2: Add A Talk Synthesis Artifact

Introduce a lightweight intermediate artifact, such as `talk_synthesis.md` or `argument_map.json`, before final report writing.

This artifact should summarize the talk-level argument, major claims, evidence flow, and slide roles. The final report writer should consume it when explaining each slide. This gives the subagent a concrete place to do whole-talk reasoning before drafting.

The first version should prefer `talk_synthesis.md` because it is easy for agent hosts to read and write. A later version can add `argument_map.json` once validation needs a structured schema.

### P2: Mark Historical Repair Plans Resolved

When final validation succeeds after a repair gate, mark the prior repair plan as resolved or superseded. This prevents a completed run from looking blocked when a user opens `agent_quality_repair_plan.json` after the fact.

## Proposed Implementation Approach

### Report Writing Prompt And Tasks

In `conference_report/report.py`, update `write_report_writer_prompt`, `agent_report_task`, and grounding task instructions.

The prompt should require a talk-level synthesis before per-slide writing. It should tell writers to hide audit scaffolding from the main report body, while preserving traceability through grounding review and provenance. It should also clarify that low-information slides may be summarized as skipped/evidence-only when the task contract allows that behavior.

The report task `quality_contract` should include the same requirements in machine-readable form so future agents see the rule even if they do not read the generated prompt carefully.

The grounding task instructions should require prose-quality review in addition to claim support. If a report is grounded but reads like a validation table, `template_or_style_issues` should be non-empty and `requires_revision` should be true.

### Dispatch Plan And Hard Gates

Extend the report dispatch plan so each worker item states why it is ready: expected slide cognition count, QA output path, dependency validation phase, and allowed output paths.

The parent agent should not dispatch a report writer when dependency validation fails. The CLI should expose this through `pipeline_state.json` and `agent_report_dispatch_plan.json`, so the parent does not guess whether a report is ready.

### Validation

In `conference_report/validate.py`, update slide coverage extraction and report-quality checks.

Coverage extraction should collect slide numbers from multiple patterns instead of only `第 N 张` headings. Style checks should flag visible audit scaffolding, repeated metadata lines, and repeated page-template openings. Report-quality failures from these checks should create `report_revision_required` issues.

Grounding validation already rejects non-empty `template_or_style_issues`; keep that behavior, but make the grounding task instructions more explicit so reviewers use the field for prose-quality failures.

### Evidence-Only Slide Handling

Use existing low-information slide detection and skipped-slide metadata as the foundation. Extend the report contract so skipped or evidence-only slides remain traceable without forcing full main-body prose. This should preserve auditability while improving reader experience.

### Feedback Artifacts

Make validation and repair artifacts more explanatory. Report-quality failures should name the failure class, identify representative excerpts or slide sections when possible, and point to the upstream artifact that should be repaired. This gives the next subagent a concrete repair target instead of a vague instruction to improve quality.

Add a sampled-audit style summary to `report_quality_validation.json` when style checks fail: marker counts, representative slide sections, and the grounding file that should have reported the style issue.

### Repair Plan State

When final validation passes and all repair task counts are zero, write a resolved marker into the repair plan or supersede it from pipeline state. The goal is to make post-run artifacts unambiguous: the run may have gone through repair, but it is no longer blocked.

## Implementation Update

The first implementation pass has landed the P0/P1 core controls:

- Report writer tasks now declare `synthesis_path`, `intermediate_output_paths`, and `slide_identity_contract`.
- The generated writer prompt requires `talk_synthesis.md` before the final Markdown report.
- Report dispatch plan items now expose dependency validation phase, expected dependency counts, and ready/not-ready status.
- Report-quality validation accepts multiple slide coverage formats, separates evidence-only rows from required main-body coverage, and flags reader-facing audit scaffolding.
- Grounding task instructions now explicitly require prose/style review through `template_or_style_issues`.
- Repair plans classify failures by quality issue class and mark historical repair plans resolved after a later successful quality pass.
- The source skill instructions now describe the same constraints for installed-skill users.

One implementation issue was found during self-review: a synthesis failure creates a report-revision task, so that revision task must also allow writing `talk_synthesis.md`. The repair manifest now carries the synthesis path in `intermediate_output_paths`, adds it to `allowed_write_paths`, and keeps it tied to provenance.

## Test Plan

Run the full test suite:

```bash
.venv/bin/python -m pytest -q
```

Add targeted tests for:

- Coverage parsing accepts `第 N 张`, `Slide N`, and `slide_index: N`.
- Reader-facing audit phrases such as `证据源为 evidence.json` fail report-quality validation.
- Repeated standalone `slide_index:` lines fail report-quality validation.
- Report dispatch is blocked or marked not ready when declared cognition/QA dependencies fail validation.
- `talk_synthesis.md` is generated or required before `report_write` once the synthesis feature is enabled.
- Repair plans classify quality failures by support, coverage, style, scaffolding, and synthesis issue types.
- Grounding reviews with non-empty `template_or_style_issues` prevent final validation from passing.
- Low-information slides can remain traceable without being forced into the main per-slide narrative.
- Non-contiguous original slide indexes do not break coverage checks or force duplicate visible metadata in report prose.
- Cross-talk transition slides can be marked evidence-only while remaining traceable.
- A completed run after repair does not leave an apparently active `blocked_gate: report_quality_repair` artifact without a resolved or superseded marker.

Use `session-10012011-installed-skill-test` as a manual acceptance reference. The improved validator should explain why the old reports are structurally valid but style-imperfect: grounded, complete, and provenance-correct, yet too visibly shaped by validation scaffolding.

## Acceptance Criteria

- Maintainers can open the Markdown design note and static HTML approval page locally.
- The design note does not contain browser cookies, API keys, private transcript dumps, or machine-specific credential material.
- The proposed implementation preserves the agent-native writing invariant: final reports are written by isolated report-writing subagents, not by the parent controller.
- Future report-quality validation can fail a grounded but mechanical report, then generate actionable repair tasks.
- Reader-facing reports preserve evidence traceability without exposing validation scaffolding as prose.
