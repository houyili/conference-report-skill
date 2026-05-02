# Repository Guidelines

## Development vs. Use Stage

This repository is an open-source project. Development-stage changes must be generic: cross-operating-system, cross-agent-platform, and suitable for conference replays, video courses, lectures, and ordinary long-form technical videos. ICLR is an important current test scenario, not the product boundary.

Keep local use-stage details out of the repository. Do not commit absolute user paths, local workspace names, API keys, browser cookies, private transcripts, media, or generated research artifacts. A maintainer's local run is treated as user acceptance testing that imitates a real user's environment; any lesson from that run must be generalized before it lands in source, docs, tests, or scripts.

After development, users should run the globally installed skill, not the checkout copy directly. The first deployment to an agent is an install; later deployments after repo changes are upgrades.

## Project Structure & Module Organization

`conference_report/` contains the Python package and CLI entry point. Core pipeline modules are split by stage: `ingest.py`, `asr.py`, `slides.py`, `dedupe.py`, `segment.py`, `report.py`, and `validate.py`; shared helpers live in `utils.py`, `config.py`, and `auth.py`. `tests/` holds unit tests. `scripts/` contains installer, upgrade, and validation helpers. `skills/conference-report/` is the canonical source for the bundled cross-agent skill, and `examples/manual_segments/` contains manual segmentation templates. Development-only generated runs may use ignored directories such as `outputs/`; real user output locations are use-stage configuration and must not be hardcoded in the repo.

## Cross-Agent Skill Distribution

The skill must remain usable by Codex, Claude Code, Antigravity, OpenClaw, and other agent hosts that support skill-like directories. Do not make the skill body depend on Codex-only behavior unless the section is explicitly labeled as a platform-specific note. Prefer agent-neutral wording such as "agent", "global skill directory", and "installed skill".

Install and upgrade use explicit user-supplied target directories only:

- First install: `python3 scripts/install_agent_skill.py install --target-dir <agent-skills-root>`
- Later upgrade: `python3 scripts/install_agent_skill.py upgrade --target-dir <agent-skills-root>`
- Multiple agents: repeat `--target-dir` for each global skill root.

Never infer or hardcode global skill directories in repository code or docs. Platform-specific paths belong in a user's local shell history, private notes, environment variables, or external platform documentation, not in this repo.

## Build, Test, and Development Commands

- `python3 -m venv .venv`: create a local virtual environment.
- `.venv/bin/python -m pip install -e ".[dev]"`: install the package plus test dependencies.
- `.venv/bin/python -m pip install -e ".[asr,dev]"`: include local ASR support for end-to-end development.
- `.venv/bin/python -m pytest -q`: run the same test command used by CI.
- `.venv/bin/conference-report --help`: smoke-test the CLI entry point.
- `.venv/bin/conference-report build URL --out outputs/run --config config.example.yaml`: run the full pipeline locally.
- `python3 scripts/install_agent_skill.py install --target-dir <agent-skills-root>`: first-time install of the bundled skill into a user-selected global skill directory.
- `python3 scripts/install_agent_skill.py upgrade --target-dir <agent-skills-root>`: refresh an existing global skill copy after development changes.
- `python3 scripts/install_git_hooks.py`: install the optional repository pre-push hook. Set `CONFERENCE_REPORT_SKILL_VALIDATOR=/path/to/quick_validate.py` to add skill validation before push.

## Coding Style & Naming Conventions

Use Python 3.10+ syntax and keep modules focused on one pipeline stage. Follow the existing style: 4-space indentation, type hints for public helpers, `Path` objects for filesystem paths, and snake_case for modules, functions, variables, and test methods. Prefer small pure helpers in `utils.py` only when they are genuinely shared. No formatter is configured, so keep imports tidy and avoid broad rewrites.

## Testing Guidelines

Tests are written with `unittest` and executed by `pytest`. Add tests under `tests/test_*.py`, name methods `test_<behavior>`, and prefer temporary directories plus mocks for filesystem, credential, and tool-lookup behavior. Run `.venv/bin/python -m pytest -q` before submitting. Broaden coverage when touching privacy redaction, credential lookup, segmentation boundaries, or generated artifact structure.

When adding install, upgrade, hook, or distribution behavior, test with temporary directories. Tests must prove target directories are user supplied and no platform-global path is baked into the implementation.

## Commit & Pull Request Guidelines

Recent commits use short imperative subjects such as `Redact sensitive page dump contents` and `Fix Windows tool lookup test`. Keep commits focused and mention user-visible behavior when relevant. Pull requests should describe the change, list verification commands, link issues when applicable, and include screenshots or artifact paths only for report or review-page output changes. Never attach private page dumps, cookies, transcripts, media, API keys, or generated conference artifacts.

At the end of a development cycle, run verification, install or upgrade the global skill copy using user-supplied target directories when a use-stage check is needed, then commit and push the branch unless the user explicitly asks to pause. Use the optional pre-push hook from `scripts/install_git_hooks.py` to guard pushes with the local test suite and any explicitly configured skill validator.

## Security & Configuration Tips

Use `OPENAI_API_KEY` or the OS credential store; do not write secrets into config files. Keep local run data in ignored paths such as `outputs/`, `raw/`, `asr/`, `slides_original/`, `talks/`, and `reports/`. User-specific research workspaces are use-stage choices and must stay out of tracked repository files.
