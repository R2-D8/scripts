#!/usr/bin/env python3
"""Convert PowerPoint presentations (PPT/PPTX) to PDF.

This script is a thin wrapper around LibreOffice ("soffice") in headless mode.

Default folders are relative to this script:
- input/:  place .ppt/.pptx here
- output/: PDFs written here

By default it scans the input folder (non-recursive) and converts every
presentation file it finds.

Notes:
- Requires LibreOffice installed and `soffice` discoverable on PATH.
- Output filenames are `<input_stem>.pdf`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RunResult:
    processed: int
    succeeded: int
    failed: int
    skipped: int


_SUPPORTED_EXTS = {".ppt", ".pptx"}


def _iter_inputs(*, input_dir: Path, recursive: bool) -> Iterable[Path]:
    if not input_dir.exists():
        return

    it = input_dir.rglob("*") if recursive else input_dir.iterdir()
    for path in sorted(it):
        if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTS:
            yield path


def _resolve_soffice(soffice_arg: str | None) -> str:
    if soffice_arg:
        candidate = Path(soffice_arg).expanduser()
        # If the user passed a path, honor it.
        if candidate.exists():
            return str(candidate)

        # Otherwise treat it like a command name.
        exe = shutil.which(soffice_arg)
        if exe:
            return exe

    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if exe:
        return exe

    raise FileNotFoundError(
        "LibreOffice not found (expected `soffice` on PATH).\n\n"
        "Install it, for example on Debian/Ubuntu:\n"
        "  sudo apt install libreoffice\n\n"
        "Or pass an explicit path via --soffice /path/to/soffice"
    )


def _planned_output_pdf(*, output_dir: Path, input_dir: Path, input_ppt: Path) -> Path:
    rel = input_ppt.relative_to(input_dir)
    return output_dir / rel.parent / f"{rel.stem}.pdf"


def convert_one(
    *,
    soffice: str,
    input_ppt: Path,
    out_dir_for_file: Path,
    timeout_s: int | None,
) -> None:
    out_dir_for_file.mkdir(parents=True, exist_ok=True)

    cmd = [
        soffice,
        "--headless",
        "--nologo",
        "--nolockcheck",
        "--nodefault",
        "--nofirststartwizard",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir_for_file),
        str(input_ppt),
    ]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or f"soffice failed with code {proc.returncode}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent

    p = argparse.ArgumentParser(
        description="Convert all PPT/PPTX files in a folder to PDFs via LibreOffice (soffice).",
    )
    p.add_argument(
        "-i",
        "--input",
        "--input-dir",
        dest="input_dir",
        type=Path,
        default=script_dir / "input",
        help="Folder containing .ppt/.pptx files (default: ./input next to the script)",
    )
    p.add_argument(
        "-o",
        "--output",
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=script_dir / "output",
        help="Folder for PDFs (default: ./output next to the script)",
    )
    p.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Also process subdirectories (preserves folder structure under output)",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output PDFs if they already exist",
    )
    p.add_argument(
        "--soffice",
        type=str,
        default=None,
        help="Explicit path to `soffice` (default: search PATH)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Per-file timeout seconds (0 = no timeout) (default: 0)",
    )
    p.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0 (useful for batch runs)",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    input_dir: Path = Path(args.input_dir).expanduser()
    output_dir: Path = Path(args.output_dir).expanduser()

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        soffice = _resolve_soffice(args.soffice)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 0 if bool(args.exit_zero) else 2

    inputs = list(_iter_inputs(input_dir=input_dir, recursive=bool(args.recursive)))
    if not inputs:
        print(f"No PPT/PPTX files found in: {input_dir}", file=sys.stderr)
        return 0

    processed = 0
    succeeded = 0
    failed = 0
    skipped = 0

    timeout_s: int | None = None
    if int(args.timeout) > 0:
        timeout_s = int(args.timeout)

    for input_ppt in inputs:
        processed += 1
        planned_out = _planned_output_pdf(output_dir=output_dir, input_dir=input_dir, input_ppt=input_ppt)

        if planned_out.exists() and not bool(args.overwrite):
            skipped += 1
            print(f"SKIP: {planned_out} (exists; use --overwrite)")
            continue

        try:
            convert_one(
                soffice=soffice,
                input_ppt=input_ppt,
                out_dir_for_file=planned_out.parent,
                timeout_s=timeout_s,
            )

            if not planned_out.exists():
                # LibreOffice is the source of truth; if it didn't produce the expected file,
                # treat it as a failure.
                raise FileNotFoundError(f"Expected output not found: {planned_out}")

            succeeded += 1
            print(f"OK: {input_ppt} -> {planned_out}")
        except subprocess.TimeoutExpired:
            failed += 1
            print(f"FAIL: {input_ppt} (timeout after {timeout_s}s)", file=sys.stderr)
        except Exception as exc:
            failed += 1
            print(f"FAIL: {input_ppt}: {exc}", file=sys.stderr)

    result = RunResult(processed=processed, succeeded=succeeded, failed=failed, skipped=skipped)
    print(
        f"Done. processed={result.processed} succeeded={result.succeeded} "
        f"failed={result.failed} skipped={result.skipped}",
        file=sys.stderr if result.failed else sys.stdout,
    )

    if bool(args.exit_zero):
        return 0
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
