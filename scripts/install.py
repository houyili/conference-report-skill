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
LOCAL_ASR_PACKAGE = "faster-whisper"


@dataclass(frozen=True)
class PackageStatus:
    name: str
    installed: bool
    version: str | None = None
    has_conflicts: bool = False
    conflict_report: str = ""


@dataclass(frozen=True)
class SkillRootCandidate:
    label: str
    path: Path
    source: str


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    try:
        subprocess.check_call(cmd, cwd=ROOT, env=env)
    except subprocess.CalledProcessError as exc:
        command = " ".join(str(part) for part in cmd)
        hint = ""
        if "pip" in cmd:
            hint = " If this happened during pip install, check network access, proxy settings, or use pre-downloaded wheels."
        raise SystemExit(f"Command failed with exit code {exc.returncode}: {command}.{hint}") from None


def venv_python(venv: Path) -> Path:
    if platform.system() == "Windows":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_command(venv: Path, name: str) -> Path:
    if platform.system() == "Windows":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def interpreter_version(python: Path | str) -> tuple[int, int, int] | None:
    try:
        proc = subprocess.run(
            [str(python), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    try:
        major, minor, patch = proc.stdout.strip().split(".", 2)
        return int(major), int(minor), int(patch)
    except ValueError:
        return None


def is_python_310_plus(python: Path | str) -> bool:
    version = interpreter_version(python)
    return bool(version and version >= (3, 10, 0))


def find_compatible_python() -> Path | None:
    candidates = [
        Path(sys.executable),
        *(Path(path) for name in ["python3.14", "python3.13", "python3.12", "python3.11", "python3.10", "python3"] if (path := shutil.which(name))),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_python_310_plus(candidate):
            return candidate
    return None


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


def dev_dependency_summary() -> str:
    return (
        "Developer dependencies currently install pytest, which is used by contributors and CI "
        "to run the test suite. pytest is not required for normal report generation."
    )


def tool_status(name: str, *, extra_path: str | None = None) -> bool:
    path = shutil.which(name, path=extra_path or os.environ.get("PATH"))
    print(f"{name}: {'found at ' + path if path else 'missing'}")
    return bool(path)


def missing_required_tool_warning(missing: list[str]) -> str:
    tools = ", ".join(missing)
    return (
        f"Warning: required system tool(s) missing: {tools}. "
        "The CLI and skill may be installed, but you cannot run the full build pipeline until these are installed."
    )


def print_system_dependency_help() -> None:
    system = platform.system()
    print("\nSystem dependencies:")
    print("- Required: ffmpeg and ffprobe")
    print("- Optional but useful: tesseract for local OCR evidence bundles")
    if system == "Darwin":
        print("  macOS/Homebrew: brew install ffmpeg tesseract")
    elif system == "Linux":
        print("  Debian/Ubuntu: sudo apt-get install ffmpeg tesseract-ocr")
        print("  Fedora: sudo dnf install ffmpeg tesseract")
    elif system == "Windows":
        print("  Windows/Chocolatey: choco install ffmpeg tesseract")
        print("  Windows/Scoop: scoop install ffmpeg tesseract")


def parse_pip_show_version(text: str) -> str | None:
    for line in text.splitlines():
        if line.lower().startswith("version:"):
            return line.split(":", 1)[1].strip()
    return None


def inspect_package(python: Path, package: str) -> PackageStatus:
    show = subprocess.run(
        [str(python), "-m", "pip", "show", package],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if show.returncode != 0:
        return PackageStatus(name=package, installed=False)
    version = parse_pip_show_version(show.stdout)
    check = subprocess.run(
        [str(python), "-m", "pip", "check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    report = (check.stdout or check.stderr or "").strip()
    return PackageStatus(
        name=package,
        installed=True,
        version=version,
        has_conflicts=check.returncode != 0,
        conflict_report=report,
    )


def version_tuple(value: str) -> tuple[int, ...]:
    pieces: list[int] = []
    for raw in value.replace("-", ".").split("."):
        if raw.isdigit():
            pieces.append(int(raw))
        else:
            break
    return tuple(pieces)


def faster_whisper_compatible(version: str | None) -> bool:
    if not version:
        return False
    parsed = version_tuple(version)
    return (1, 1) <= parsed < (2,)


def print_package_status(status: PackageStatus) -> None:
    print(f"\nLocal ASR package check: {status.name}")
    if not status.installed:
        print("- Not installed in the selected Python environment.")
        return
    print(f"- Installed version: {status.version or 'unknown'}")
    if status.name == LOCAL_ASR_PACKAGE:
        if faster_whisper_compatible(status.version):
            print("- Version is compatible with this project range: >=1.1,<2.")
        else:
            print("- Version is outside this project range: >=1.1,<2.")
    if status.has_conflicts:
        print("- pip check reported dependency conflicts:")
        print(status.conflict_report)
    else:
        print(f"- pip check: {status.conflict_report or 'no broken requirements found'}")


def candidate_skill_roots(home: Path, env: dict[str, str]) -> list[SkillRootCandidate]:
    candidates: list[SkillRootCandidate] = []
    seen: set[Path] = set()

    def add(label: str, path: Path, source: str) -> None:
        expanded = path.expanduser()
        if not expanded.exists():
            return
        resolved = expanded.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(SkillRootCandidate(label=label, path=expanded, source=source))

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
            add(label, Path(value), key)

    home_keys = {
        "CODEX_HOME": "Codex",
        "CLAUDE_HOME": "Claude Code",
        "ANTIGRAVITY_HOME": "Antigravity",
        "OPENCLAW_HOME": "OpenClaw",
    }
    for key, label in home_keys.items():
        value = env.get(key)
        if value:
            add(label, Path(value) / "skills", f"{key}/skills")

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


def conda_executable() -> str | None:
    return shutil.which("conda")


def conda_env_python(conda: str, env_name: str) -> Path:
    proc = subprocess.run(
        [conda, "run", "-n", env_name, "python", "-c", "import sys; print(sys.executable)"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return Path(proc.stdout.strip().splitlines()[-1])


def choose_python_environment(args: argparse.Namespace) -> tuple[Path, Path | None, bool]:
    conda = conda_executable()
    compatible_python = find_compatible_python()
    options = []
    if compatible_python:
        options.append(("venv", f"Create/use project .venv with {compatible_python}: isolated and easiest to remove"))
    if conda:
        options.extend([
            ("conda-existing", "Use an existing conda environment"),
            ("conda-create", "Create a new conda environment"),
        ])
    if is_python_310_plus(sys.executable):
        options.append(("current", "Install into the current Python environment"))
    if not options:
        raise SystemExit(
            "Python 3.10+ is required to install conference-report. "
            "Install Python 3.10+ or conda, then rerun: python3 scripts/install.py"
        )

    print("\nPython environment")
    print("This controls where Python packages are installed. The recommended choice is project .venv.")
    choice = choose("Where should dependencies be installed?", options, default=1)

    if choice == "current":
        return Path(sys.executable), None, True
    if choice == "conda-existing":
        assert conda is not None
        env_name = input("Enter the conda environment name to use: ").strip()
        if not env_name:
            raise SystemExit("No conda environment name entered.")
        return conda_env_python(conda, env_name), None, True
    if choice == "conda-create":
        assert conda is not None
        env_name = input("Enter a new conda environment name [conference-report]: ").strip() or "conference-report"
        run([conda, "create", "-y", "-n", env_name, "python=3.10", "pip"])
        return conda_env_python(conda, env_name), None, True

    venv = args.venv
    if not venv.exists():
        assert compatible_python is not None
        run([str(compatible_python), "-m", "venv", str(venv)])
    python = venv_python(venv)
    if not is_python_310_plus(python):
        raise SystemExit(f"{python} is not Python 3.10+. Remove or recreate {venv} with Python 3.10+.")
    return python, venv, False


def maybe_install_system_deps() -> None:
    if platform.system() != "Darwin":
        print_system_dependency_help()
        return
    if shutil.which("brew") is None:
        print_system_dependency_help()
        return
    packages = []
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        packages.append("ffmpeg")
    if shutil.which("tesseract") is None and yes("Install optional tesseract OCR with Homebrew?"):
        packages.append("tesseract")
    if packages and yes(f"Install Homebrew packages now: {' '.join(packages)}?"):
        run(["brew", "install", *packages])


def prompt_skill_install() -> None:
    print("\nGlobal agent skill install")
    print("The CLI is installed in this Python environment. The skill must be copied into each agent's global skills root.")
    print("The installer can suggest existing local roots, but you choose the target.")
    if not yes("Install the global skill now?", default=True):
        print("Skipping skill install. You can run scripts/install_agent_skill.py later.")
        return

    candidates = candidate_skill_roots(Path.home(), os.environ)
    target: Path | None = None
    if candidates:
        print("\nFound candidate skill roots:")
        for index, item in enumerate(candidates, start=1):
            print(f"  {index}. {item.label}: {item.path} ({item.source})")
        answer = input("Choose a number, or type another skills root path: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            target = candidates[int(answer) - 1].path
        elif answer:
            target = Path(answer).expanduser()
    else:
        print("No existing agent skill roots were found. Check your agent docs and paste its skills root.")
        answer = input("Agent skills root path: ").strip()
        if answer:
            target = Path(answer).expanduser()

    if target is None:
        print("No skill target selected; skipping global skill install.")
        return

    from install_agent_skill import DEFAULT_SKILL_NAME, default_source, install_skill

    upgrade = (target / DEFAULT_SKILL_NAME).exists()
    if upgrade:
        print(f"{target / DEFAULT_SKILL_NAME} already exists; this will upgrade it.")
    installed = install_skill(default_source(DEFAULT_SKILL_NAME), [target], DEFAULT_SKILL_NAME, upgrade=upgrade)
    print(f"{'Upgraded' if upgrade else 'Installed'} skill to {installed[0]}")


def editable_spec(with_local_asr: bool, with_dev: bool) -> str:
    extras = []
    if with_local_asr:
        extras.append("asr")
    if with_dev:
        extras.append("dev")
    return ".[{}]".format(",".join(extras)) if extras else "."


def guided_install(args: argparse.Namespace) -> int:
    print("Conference Report guided installer")
    print("You can press Enter to accept the recommended option at each step.")

    profile = choose(
        "Install profile",
        [
            ("user", "Normal user install: CLI and runtime dependencies"),
            ("dev", "Contributor/dev install: also install test tools"),
        ],
        default=1,
    )
    with_dev = profile == "dev"
    if with_dev:
        print(dev_dependency_summary())
    else:
        print("Normal install skips developer dependencies such as pytest; they are not required for report generation.")

    python, venv, install_into_current = choose_python_environment(args)
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])

    asr_status = inspect_package(python, LOCAL_ASR_PACKAGE)
    print_package_status(asr_status)
    asr_recommended = (
        not asr_status.installed
        or not faster_whisper_compatible(asr_status.version)
        or asr_status.has_conflicts
    )
    print("\nLocal ASR lets the tool transcribe videos when platform subtitles are missing.")
    with_local_asr = yes("Install or repair local ASR support with faster-whisper?", default=asr_recommended)

    run([str(python), "-m", "pip", "install", "-e", editable_spec(with_local_asr, with_dev)])

    maybe_install_system_deps()

    path = os.environ.get("PATH", "")
    if venv is not None:
        bin_dir = str(venv_command(venv, "conference-report").parent)
        path = bin_dir + os.pathsep + path
    print("\nTool check:")
    tool_status("conference-report", extra_path=path)
    tool_status("yt-dlp", extra_path=path)
    missing_required_tools = []
    if not tool_status("ffmpeg"):
        missing_required_tools.append("ffmpeg")
    if not tool_status("ffprobe"):
        missing_required_tools.append("ffprobe")
    tool_status("tesseract")
    if missing_required_tools:
        print("\n" + missing_required_tool_warning(missing_required_tools))

    command = Path("conference-report") if install_into_current else venv_command(venv or args.venv, "conference-report")
    print("\nOpenAI API key")
    print("Without a key, the report step can still emit evidence bundles instead of final automated reports.")
    status = subprocess.run([str(command), "auth", "status", "openai"], cwd=ROOT)
    if status.returncode != 0 and yes("Store an OpenAI API key in your system credential store now?", default=False):
        run([str(command), "auth", "set", "openai"])

    prompt_skill_install()

    if missing_required_tools:
        print("\nInstall completed with missing system tools. After installing them, try:")
    else:
        print("\nDone. Try:")
    print(f"  {command} build URL --out outputs/run --config config.example.yaml")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install conference-report and guide credential setup.")
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv", help="Virtual environment path.")
    parser.add_argument("--no-venv", action="store_true", help="Install into the current Python environment.")
    parser.add_argument("--with-local-asr", action="store_true", help="Install faster-whisper for local ASR fallback.")
    parser.add_argument("--with-dev", action="store_true", help="Install test dependencies.")
    parser.add_argument("--install-system-deps", action="store_true", help="Offer system dependency install help; on macOS can use Homebrew.")
    parser.add_argument("--skip-key", action="store_true", help="Do not prompt for an OpenAI API key.")
    args = parser.parse_args()

    guided = len(sys.argv) == 1
    if guided:
        return guided_install(args)

    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ is required for non-interactive install. Use Python 3.10+ or run the guided installer with conda available.")

    if args.no_venv:
        python = Path(sys.executable)
    else:
        if not args.venv.exists():
            run([sys.executable, "-m", "venv", str(args.venv)])
        python = venv_python(args.venv)

    editable = editable_spec(args.with_local_asr, args.with_dev)
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", "-e", editable])

    if args.install_system_deps:
        maybe_install_system_deps()
    else:
        print_system_dependency_help()

    path = os.environ.get("PATH", "")
    if not args.no_venv:
        bin_dir = str(venv_command(args.venv, "conference-report").parent)
        path = bin_dir + os.pathsep + path
    print("\nTool check:")
    tool_status("conference-report", extra_path=path)
    tool_status("yt-dlp", extra_path=path)
    tool_status("ffmpeg")
    tool_status("ffprobe")
    tool_status("tesseract")

    command = venv_command(args.venv, "conference-report") if not args.no_venv else Path("conference-report")
    if not args.skip_key:
        status = subprocess.run([str(command), "auth", "status", "openai"], cwd=ROOT)
        if status.returncode != 0 and yes("Store an OpenAI API key in your system credential store now?"):
            run([str(command), "auth", "set", "openai"])

    print("\nDone. Try:")
    if args.no_venv:
        print("  conference-report build URL --out outputs/run --config config.example.yaml")
    else:
        print(f"  {command} build URL --out outputs/run --config config.example.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
