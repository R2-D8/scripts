#!/usr/bin/env python3
"""Download and install a local static ffmpeg build (Linux).

Goal: make this repo usable on a fresh machine without sudo/apt.

Installs into:
  tools/ffmpeg/bin/{ffmpeg,ffprobe}

Source: https://johnvansickle.com/ffmpeg/ (GPLv3 static builds)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def _arch_tag(machine: str) -> str:
    m = machine.lower()
    if m in {"x86_64", "amd64"}:
        return "amd64"
    if m in {"i386", "i686"}:
        return "i686"
    if m in {"aarch64", "arm64"}:
        return "arm64"
    if m in {"armv7l", "armv7", "armhf"}:
        return "armhf"
    if m in {"armv6l", "armel"}:
        return "armel"
    raise RuntimeError(f"Unsupported CPU arch for static ffmpeg installer: {machine}")


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "scripts-repo/ffmpeg-installer (urllib)"
        },
    )
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _top_level_dir(extract_dir: Path) -> Path:
    # Most tarballs contain a single top-level folder.
    children = [p for p in extract_dir.iterdir() if p.is_dir()]
    if len(children) == 1:
        return children[0]
    # Fallback: pick the newest directory.
    if children:
        return sorted(children, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    raise RuntimeError("Unexpected archive layout: no extracted directories")


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    tools_dir = repo_root / "tools"
    target_dir = tools_dir / "ffmpeg"
    bin_dir = target_dir / "bin"

    if platform.system().lower() != "linux":
        print(
            "This installer currently supports Linux only.\n"
            "Please install ffmpeg via your package manager (or add a platform-specific downloader).",
            file=sys.stderr,
        )
        return 2

    machine = platform.machine()
    try:
        tag = _arch_tag(machine)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 2

    url = f"https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-{tag}-static.tar.xz"

    # If already installed, do nothing.
    ffmpeg_path = bin_dir / "ffmpeg"
    ffprobe_path = bin_dir / "ffprobe"
    if ffmpeg_path.exists() and ffprobe_path.exists():
        return 0

    bin_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ffmpeg-install-") as td:
        tmp = Path(td)
        archive = tmp / f"ffmpeg-release-{tag}-static.tar.xz"
        extract_dir = tmp / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        print(f"Downloading: {url}")
        try:
            _download(url, archive)
        except Exception as e:
            print(f"Failed downloading ffmpeg archive: {e}", file=sys.stderr)
            return 2

        print("Extracting...")
        try:
            with tarfile.open(archive, mode="r:xz") as tf:
                tf.extractall(extract_dir)
        except Exception as e:
            # Some Python builds are compiled without lzma support.
            # Fallback: use system 'tar' if present.
            tar_exe = shutil.which("tar")
            if tar_exe:
                try:
                    subprocess.run(
                        [tar_exe, "-xJf", str(archive), "-C", str(extract_dir)],
                        check=True,
                    )
                except Exception as e2:
                    print(
                        "Failed extracting .tar.xz (Python and system tar both failed).\n"
                        "Your Python may lack lzma support and your tar may not support xz.\n"
                        "Workaround: install ffmpeg via your package manager.",
                        file=sys.stderr,
                    )
                    print(f"Python error: {e}", file=sys.stderr)
                    print(f"tar error: {e2}", file=sys.stderr)
                    return 2
            else:
                print(
                    "Failed extracting .tar.xz. Your Python build may lack lzma support, and 'tar' was not found.\n"
                    "Workaround: install ffmpeg via your package manager.",
                    file=sys.stderr,
                )
                print(f"Details: {e}", file=sys.stderr)
                return 2

        top = _top_level_dir(extract_dir)
        src_ffmpeg = top / "ffmpeg"
        src_ffprobe = top / "ffprobe"

        if not src_ffmpeg.exists():
            print("Archive did not contain expected ffmpeg binary", file=sys.stderr)
            return 2
        if not src_ffprobe.exists():
            print("Archive did not contain expected ffprobe binary", file=sys.stderr)
            return 2

        shutil.copy2(src_ffmpeg, ffmpeg_path)
        shutil.copy2(src_ffprobe, ffprobe_path)

    # Ensure executable bit.
    ffmpeg_path.chmod(ffmpeg_path.stat().st_mode | 0o111)
    ffprobe_path.chmod(ffprobe_path.stat().st_mode | 0o111)

    # Write a small marker.
    (target_dir / "SOURCE.txt").write_text(
        "Downloaded from https://johnvansickle.com/ffmpeg/ (static GPLv3 builds).\n",
        encoding="utf-8",
    )

    print(f"Installed: {ffmpeg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
