#!/usr/bin/env python3
"""Bootstrap this repo on a fresh machine.

Goal: after installing only Python 3 + venv support, running this script should:
- create the repo-wide virtualenv at .venv/
- install all Python package deps from requirements.txt
- download a local static ffmpeg into tools/ffmpeg/

Usage:
  python3 tools/bootstrap.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    venv_python = repo_root / ".venv" / "bin" / "python"

    requirements = repo_root / "requirements.txt"
    if not requirements.exists():
        print(f"requirements.txt not found at: {requirements}", file=sys.stderr)
        return 2

    print("[1/3] Creating venv (.venv/)")
    _run(["python3", "-m", "venv", str(repo_root / ".venv")])

    print("[2/3] Installing Python deps")
    _run([str(venv_python), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
    _run([str(venv_python), "-m", "pip", "install", "-r", str(requirements)])

    print("[3/3] Installing ffmpeg (local static build)")
    _run([str(venv_python), str(repo_root / "tools" / "install_ffmpeg_static.py")])

    print("Done. You can now run targets via 'make <target>' or call .venv/bin/python directly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
