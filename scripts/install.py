#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT, env=env)


def venv_python(venv: Path) -> Path:
    if platform.system() == "Windows":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_command(venv: Path, name: str) -> Path:
    if platform.system() == "Windows":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def yes(prompt: str, *, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def tool_status(name: str, *, extra_path: str | None = None) -> bool:
    path = shutil.which(name, path=extra_path or os.environ.get("PATH"))
    print(f"{name}: {'found at ' + path if path else 'missing'}")
    return bool(path)


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Install conference-report and guide credential setup.")
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv", help="Virtual environment path.")
    parser.add_argument("--no-venv", action="store_true", help="Install into the current Python environment.")
    parser.add_argument("--with-local-asr", action="store_true", help="Install faster-whisper for local ASR fallback.")
    parser.add_argument("--with-dev", action="store_true", help="Install test dependencies.")
    parser.add_argument("--install-system-deps", action="store_true", help="Offer system dependency install help; on macOS can use Homebrew.")
    parser.add_argument("--skip-key", action="store_true", help="Do not prompt for an OpenAI API key.")
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ is required.")

    if args.no_venv:
        python = Path(sys.executable)
    else:
        if not args.venv.exists():
            run([sys.executable, "-m", "venv", str(args.venv)])
        python = venv_python(args.venv)

    extras = []
    if args.with_local_asr:
        extras.append("asr")
    if args.with_dev:
        extras.append("dev")
    editable = ".[{}]".format(",".join(extras)) if extras else "."
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
