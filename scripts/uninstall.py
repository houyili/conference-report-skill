#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "conference-report"
PROJECT_PACKAGES = ["conference-report"]
OPTIONAL_ASR_PACKAGES = ["faster-whisper"]
ASR_HEAVY_DEPENDENCIES = ["ctranslate2", "onnxruntime", "av"]
SHARED_PACKAGES = ["openai", "keyring", "yt-dlp"]


@dataclass(frozen=True)
class PackageInfo:
    name: str
    installed: bool
    version: str | None = None
    required_by: list[str] | None = None


@dataclass(frozen=True)
class SkillInstall:
    label: str
    path: Path
    source: str


def yes(prompt: str, *, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def choose(prompt: str, options: list[tuple[str, str]], *, default: int = 1) -> str:
    print(f"\n{prompt}")
    for index, (_value, label) in enumerate(options, start=1):
        suffix = " (Recommended)" if index == default else ""
        print(f"  {index}. {label}{suffix}")
    while True:
        answer = input(f"Choose 1-{len(options)} [default {default}]: ").strip()
        if not answer:
            return options[default - 1][0]
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        print("Please enter a number from the list.")


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    try:
        subprocess.check_call(cmd, cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {' '.join(cmd)}") from None


def parse_pip_show(name: str, text: str) -> PackageInfo:
    version: str | None = None
    required_by: list[str] = []
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        if key.lower() == "version":
            version = value.strip()
        elif key.lower() == "required-by":
            raw = value.strip()
            required_by = [item.strip() for item in raw.split(",") if item.strip()]
    return PackageInfo(name=name, installed=True, version=version, required_by=required_by)


def inspect_package(python: Path, name: str) -> PackageInfo:
    proc = subprocess.run(
        [str(python), "-m", "pip", "show", name],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return PackageInfo(name=name, installed=False, required_by=[])
    return parse_pip_show(name, proc.stdout)


def pip_check(python: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(python), "-m", "pip", "check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode == 0, (proc.stdout or proc.stderr or "").strip()


def default_package_actions(packages: list[PackageInfo]) -> dict[str, bool]:
    actions: dict[str, bool] = {}
    for package in packages:
        external_required_by = [name for name in (package.required_by or []) if name not in PROJECT_PACKAGES]
        if not package.installed:
            actions[package.name] = False
        elif package.name in PROJECT_PACKAGES:
            actions[package.name] = True
        elif package.name in OPTIONAL_ASR_PACKAGES and not external_required_by:
            actions[package.name] = True
        else:
            actions[package.name] = False
    return actions


def uninstall_packages(python: Path, packages: list[str], *, dry_run: bool = False) -> None:
    if not packages:
        return
    cmd = [str(python), "-m", "pip", "uninstall", "-y", *packages]
    if dry_run:
        print("+ " + " ".join(cmd))
        return
    run(cmd)


def remove_tree(path: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        print(f"+ rm -rf {path}")
        return
    shutil.rmtree(path)


def candidate_skill_installs(home: Path, env: dict[str, str], skill_name: str = SKILL_NAME) -> list[SkillInstall]:
    candidates: list[SkillInstall] = []
    seen: set[Path] = set()

    def add(label: str, root: Path, source: str) -> None:
        path = root.expanduser() / skill_name
        if not path.exists():
            return
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(SkillInstall(label=label, path=path, source=source))

    env_roots = {
        "AGENT_SKILLS_DIR": "Agent skills",
        "CODEX_SKILLS_DIR": "Codex",
        "CLAUDE_SKILLS_DIR": "Claude Code",
        "ANTIGRAVITY_SKILLS_DIR": "Antigravity",
        "OPENCLAW_SKILLS_DIR": "OpenClaw",
    }
    for key, label in env_roots.items():
        value = env.get(key)
        if value:
            add(label, Path(value), key)

    home_roots = [
        ("Codex", ".codex/skills"),
        ("Claude Code", ".claude/skills"),
        ("Antigravity", ".antigravity/skills"),
        ("OpenClaw", ".openclaw/skills"),
        ("Generic agent", ".agents/skills"),
    ]
    for label, rel in home_roots:
        add(label, home / rel, f"existing ~/{rel}")
    return candidates


def command_python(command_name: str = "conference-report") -> Path | None:
    command = shutil.which(command_name)
    if not command:
        return None
    command_path = Path(command)
    suffix = ".exe" if platform.system() == "Windows" else ""
    python = command_path.parent / f"python{suffix}"
    return python if python.exists() else Path(sys.executable)


def common_python_candidates() -> list[Path]:
    candidates: list[Path] = []
    for path in [
        command_python(),
        ROOT / ".venv" / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python"),
        Path("/opt/anaconda3/bin/python"),
        Path("/opt/miniconda3/bin/python"),
        Path(sys.executable),
    ]:
        if path and path.exists() and path not in candidates:
            candidates.append(path)
    return candidates


def select_python() -> Path:
    candidates = []
    for path in common_python_candidates():
        info = inspect_package(path, "conference-report")
        if info.installed:
            version = f" {info.version}" if info.version else ""
            candidates.append((str(path), f"{path} (conference-report{version})"))
    if not candidates:
        manual = input("No installed conference-report package was detected. Enter Python path to inspect, or leave blank to skip Python package uninstall: ").strip()
        if not manual:
            return Path("")
        return Path(manual).expanduser()
    choice = choose("Python environment to uninstall from", candidates, default=1)
    return Path(choice)


def system_tool_policy_text() -> str:
    return (
        "System tool policy: tesseract is optional and can be offered for removal when Homebrew installed it; "
        "ffmpeg is required by the pipeline but is shared by many tools, so this uninstaller never removes ffmpeg by default."
    )


def brew_package_installed(package: str) -> bool:
    brew = shutil.which("brew")
    if not brew:
        return False
    proc = subprocess.run([brew, "list", "--versions", package], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def maybe_uninstall_tesseract(*, dry_run: bool = False) -> None:
    if not brew_package_installed("tesseract"):
        return
    print("\nSystem tools")
    print(system_tool_policy_text())
    if yes("Uninstall Homebrew tesseract?", default=False):
        cmd = ["brew", "uninstall", "tesseract"]
        if dry_run:
            print("+ " + " ".join(cmd))
        else:
            run(cmd)


def delete_openai_key(command: Path, *, dry_run: bool = False) -> None:
    if not command or not command.exists():
        return
    if not yes("Delete the stored OpenAI API key for conference-report?", default=False):
        return
    cmd = [str(command), "auth", "delete", "openai"]
    if dry_run:
        print("+ " + " ".join(cmd))
    else:
        run(cmd)


def command_for_python(python: Path) -> Path:
    suffix = ".exe" if platform.system() == "Windows" else ""
    return python.parent / f"conference-report{suffix}"


def guided_uninstall(*, dry_run: bool = False) -> int:
    print("Conference Report guided uninstaller")
    print("Safe defaults remove this project and installed skills, while leaving shared credentials and system tools alone.")
    print("Generated run workspaces are not removed; delete those separately only when you no longer need them.")

    python = select_python()
    packages_to_remove: list[str] = []
    command = command_for_python(python) if str(python) else Path("")
    if str(python):
        packages = [inspect_package(python, name) for name in PROJECT_PACKAGES + OPTIONAL_ASR_PACKAGES + ASR_HEAVY_DEPENDENCIES + SHARED_PACKAGES]
        defaults = default_package_actions(packages)
        print("\nPython packages")
        for package in packages:
            if package.installed:
                version = f" {package.version}" if package.version else ""
                required_by = f"; required by: {', '.join(package.required_by or [])}" if package.required_by else ""
                default = defaults.get(package.name, False)
                if yes(f"Uninstall {package.name}{version}{required_by}?", default=default):
                    packages_to_remove.append(package.name)
        delete_openai_key(command, dry_run=dry_run)
        uninstall_packages(python, packages_to_remove, dry_run=dry_run)
        clean, report = pip_check(python)
        if clean:
            print(f"\nDependency check: {report or 'No broken requirements found.'}")
        else:
            print("\nWarning: pip check still reports dependency issues in this environment:")
            print(report)

    installs = candidate_skill_installs(Path.home(), os.environ)
    if installs:
        print("\nGlobal agent skills")
        for install in installs:
            if yes(f"Remove {install.label} skill at {install.path}?", default=True):
                remove_tree(install.path, dry_run=dry_run)
    else:
        print("\nNo global conference-report skill installs were detected.")

    maybe_uninstall_tesseract(dry_run=dry_run)

    print("\nUninstall flow complete.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely uninstall conference-report packages and agent skill copies.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without removing anything.")
    args = parser.parse_args(argv)
    return guided_uninstall(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
