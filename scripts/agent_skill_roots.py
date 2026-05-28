from __future__ import annotations

import re
from pathlib import Path


OPENCLAW_WORKSPACE_ENV_KEYS = (
    "OPENCLAW_WORKSPACE",
    "OPENCLAW_WORKSPACE_DIR",
    "OPENCLAW_PERSONA_WORKSPACE",
)


def expand_home_path(value: str, home: Path) -> Path:
    raw = value.strip().strip("'\"")
    if raw == "~":
        return home
    if raw.startswith("~/"):
        return home / raw[2:]
    return Path(raw).expanduser()


def openclaw_workspace_dirs(home: Path, env: dict[str, str]) -> list[Path]:
    workspaces: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        expanded = path.expanduser()
        if not expanded.exists() or not expanded.is_dir():
            return
        resolved = expanded.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        workspaces.append(expanded)

    for key in OPENCLAW_WORKSPACE_ENV_KEYS:
        value = env.get(key)
        if value:
            add(expand_home_path(value, home))

    openclaw_home = expand_home_path(env.get("OPENCLAW_HOME", "~/.openclaw"), home)
    if openclaw_home.exists():
        for pattern in ("workspace-*", "workspace_*", "workspace"):
            for candidate in sorted(openclaw_home.glob(pattern)):
                add(candidate)
    return workspaces


def openclaw_tools_skill_roots(tools_path: Path, home: Path) -> list[tuple[str, Path, str]]:
    if not tools_path.exists():
        return []
    roots: list[tuple[str, Path, str]] = []
    pattern = re.compile(r"^\s*-?\s*(local_skills_root|shared_skills_root)\s*=\s*(.+?)\s*$")
    try:
        text = tools_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        key, raw_value = match.groups()
        raw_value = raw_value.split("#", 1)[0].strip()
        if not raw_value:
            continue
        label = "OpenClaw workspace" if key == "local_skills_root" else "OpenClaw shared"
        roots.append((label, expand_home_path(raw_value, home), f"{tools_path} {key}"))
    return roots


def openclaw_workspace_skill_roots(home: Path, env: dict[str, str]) -> list[tuple[str, Path, str]]:
    roots: list[tuple[str, Path, str]] = []
    for workspace in openclaw_workspace_dirs(home, env):
        skills_dir = workspace / "skills"
        if skills_dir.exists():
            roots.append(("OpenClaw workspace", skills_dir, f"existing {workspace.name}/skills"))
        roots.extend(openclaw_tools_skill_roots(workspace / "TOOLS.md", home))
    return roots


def candidate_skill_root_entries(home: Path, env: dict[str, str]) -> list[tuple[str, Path, str]]:
    candidates: list[tuple[str, Path, str]] = []
    seen: set[Path] = set()

    def add(label: str, path: Path, source: str) -> None:
        expanded = path.expanduser()
        if not expanded.exists():
            return
        resolved = expanded.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append((label, expanded, source))

    env_keys = {
        "AGENT_SKILLS_DIR": "Agent skills",
        "CODEX_SKILLS_DIR": "Codex",
        "CLAUDE_SKILLS_DIR": "Claude Code",
        "ANTIGRAVITY_SKILLS_DIR": "Antigravity",
        "OPENCLAW_SKILLS_DIR": "OpenClaw",
    }
    for key, label in env_keys.items():
        value = env.get(key)
        if value:
            add(label, expand_home_path(value, home), key)

    home_keys = {
        "CODEX_HOME": "Codex",
        "CLAUDE_HOME": "Claude Code",
        "ANTIGRAVITY_HOME": "Antigravity",
        "OPENCLAW_HOME": "OpenClaw",
    }
    for key, label in home_keys.items():
        value = env.get(key)
        if value:
            add(label, expand_home_path(value, home) / "skills", f"{key}/skills")

    for label, path, source in openclaw_workspace_skill_roots(home, env):
        add(label, path, source)

    known_relative = [
        ("Codex", ".codex/skills"),
        ("Claude Code", ".claude/skills"),
        ("Antigravity", ".antigravity/skills"),
        ("OpenClaw", ".openclaw/skills"),
        ("Generic agent", ".agents/skills"),
    ]
    for label, rel in known_relative:
        add(label, home / rel, f"existing ~/{rel}")
    return candidates
