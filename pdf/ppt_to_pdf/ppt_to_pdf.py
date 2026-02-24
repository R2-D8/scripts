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
import os
import shutil
import tempfile
import urllib.parse
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TypeVar


def _physical_cpu_cores() -> int | None:
    """Best-effort physical core count.

    On Linux, prefer `lscpu` if available; otherwise parse /proc/cpuinfo.
    Returns None if it cannot be determined.
    """

    if not sys.platform.startswith("linux"):
        return None

    try:
        proc = subprocess.run(
            ["lscpu", "-p=CORE,SOCKET"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            pairs: set[tuple[str, str]] = set()
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2 and parts[0] and parts[1]:
                    pairs.add((parts[0], parts[1]))
            if pairs:
                return len(pairs)
    except Exception:
        pass

    try:
        cpuinfo = Path("/proc/cpuinfo")
        if not cpuinfo.exists():
            return None
        physical_id: str | None = None
        core_id: str | None = None
        pairs2: set[tuple[str, str]] = set()
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                if physical_id is not None and core_id is not None:
                    pairs2.add((physical_id, core_id))
                physical_id = None
                core_id = None
                continue
            if line.lower().startswith("physical id"):
                physical_id = line.split(":", 1)[-1].strip()
            elif line.lower().startswith("core id"):
                core_id = line.split(":", 1)[-1].strip()
        if physical_id is not None and core_id is not None:
            pairs2.add((physical_id, core_id))
        if pairs2:
            return len(pairs2)
    except Exception:
        return None

    return None


@dataclass(frozen=True)
class RunResult:
    processed: int
    succeeded: int
    failed: int
    skipped: int


_SUPPORTED_EXTS = {".ppt", ".pptx"}


@dataclass(frozen=True)
class _WorkItem:
    input_ppt: Path
    output_pdf: Path


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


def _default_jobs() -> int:
    """Default parallelism: one job per physical core (best-effort)."""
    n = _physical_cpu_cores()
    if n is None:
        try:
            n = int(os.cpu_count() or 1)
        except Exception:
            n = 1
    return max(1, int(n))


def _user_installation_arg(profile_dir: Path) -> str:
    # LibreOffice expects a file URL.
    url = urllib.parse.urlunparse(("file", "", str(profile_dir), "", "", ""))
    return f"-env:UserInstallation={url}"


def _run_soffice_convert(
    *,
    soffice: str,
    inputs: list[Path],
    out_dir: Path,
    timeout_s: int | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Use an isolated profile to make parallel `soffice` runs reliable.
    with tempfile.TemporaryDirectory(prefix="ppt_to_pdf_profile_") as tmp:
        profile_dir = Path(tmp)
        cmd = [
            soffice,
            "--headless",
            "--nologo",
            "--nolockcheck",
            "--nodefault",
            "--nofirststartwizard",
            _user_installation_arg(profile_dir),
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            *[str(p) for p in inputs],
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


T = TypeVar("T")


def _split_evenly(items: list[T], parts: int) -> list[list[T]]:
    if parts <= 1:
        return [items]
    buckets: list[list[T]] = [[] for _ in range(parts)]
    for idx, item in enumerate(items):
        buckets[idx % parts].append(item)
    return [b for b in buckets if b]


def _worker_convert_group(
    *,
    soffice: str,
    pairs: list[tuple[str, str]],
    out_dir: str,
    timeout_s: int | None,
    no_batch: bool,
) -> list[tuple[str, str, bool, str | None]]:
    """Worker entrypoint for ProcessPoolExecutor (must be top-level).

    Returns per-file tuples: (input, output, ok, error_message)
    """
    items = [(Path(i), Path(o)) for i, o in pairs]
    out_dir_p = Path(out_dir)

    def _check_outputs() -> list[tuple[str, str, bool, str | None]]:
        out: list[tuple[str, str, bool, str | None]] = []
        for inp, outp in items:
            ok = outp.exists()
            out.append((str(inp), str(outp), ok, None if ok else "Expected output not found"))
        return out

    try:
        if no_batch:
            for inp, _outp in items:
                _run_soffice_convert(soffice=soffice, inputs=[inp], out_dir=out_dir_p, timeout_s=timeout_s)
        else:
            # Approximate per-file timeout: scale by group size.
            batch_timeout: int | None = None
            if timeout_s is not None:
                batch_timeout = max(timeout_s, 1) * max(len(items), 1)
            _run_soffice_convert(
                soffice=soffice,
                inputs=[inp for inp, _ in items],
                out_dir=out_dir_p,
                timeout_s=batch_timeout,
            )
        return _check_outputs()
    except subprocess.TimeoutExpired:
        # Fall back to per-file conversion for more granular results.
        results: list[tuple[str, str, bool, str | None]] = []
        for inp, outp in items:
            try:
                _run_soffice_convert(soffice=soffice, inputs=[inp], out_dir=out_dir_p, timeout_s=timeout_s)
                ok = outp.exists()
                results.append((str(inp), str(outp), ok, None if ok else "Expected output not found"))
            except subprocess.TimeoutExpired:
                results.append((str(inp), str(outp), False, f"timeout after {timeout_s}s"))
            except Exception as exc:
                results.append((str(inp), str(outp), False, str(exc)))
        return results
    except Exception as exc:
        # Batch failed; fall back to per-file.
        results: list[tuple[str, str, bool, str | None]] = []
        for inp, outp in items:
            try:
                _run_soffice_convert(soffice=soffice, inputs=[inp], out_dir=out_dir_p, timeout_s=timeout_s)
                ok = outp.exists()
                results.append((str(inp), str(outp), ok, None if ok else "Expected output not found"))
            except subprocess.TimeoutExpired:
                results.append((str(inp), str(outp), False, f"timeout after {timeout_s}s"))
            except Exception as exc2:
                results.append((str(inp), str(outp), False, str(exc2)))
        # If even per-file didn't run, attach original error to the first.
        if results and all((not ok) for _i, _o, ok, _e in results):
            i0, o0, _ok0, e0 = results[0]
            results[0] = (i0, o0, False, e0 or str(exc))
        return results


def convert_one(
    *,
    soffice: str,
    input_ppt: Path,
    out_dir_for_file: Path,
    timeout_s: int | None,
) -> None:
    _run_soffice_convert(
        soffice=soffice,
        inputs=[input_ppt],
        out_dir=out_dir_for_file,
        timeout_s=timeout_s,
    )


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
        "-j",
        "--jobs",
        type=int,
        default=_default_jobs(),
        help="Parallel LibreOffice jobs (default: %(default)s)",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output PDFs if they already exist",
    )
    p.add_argument(
        "--no-batch",
        action="store_true",
        help="Disable batching (slower, but can help diagnose LibreOffice issues)",
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

    # Plan work and apply overwrite/skip policy up-front.
    work: list[_WorkItem] = []
    planned_outputs: dict[Path, Path] = {}
    for input_ppt in inputs:
        processed += 1
        planned_out = _planned_output_pdf(output_dir=output_dir, input_dir=input_dir, input_ppt=input_ppt)

        other = planned_outputs.get(planned_out)
        if other is not None:
            print(
                "Two inputs map to the same output PDF (ambiguous).\n"
                f"  output: {planned_out}\n"
                f"  inputs: {other} and {input_ppt}",
                file=sys.stderr,
            )
            return 0 if bool(args.exit_zero) else 2
        planned_outputs[planned_out] = input_ppt

        if planned_out.exists() and not bool(args.overwrite):
            skipped += 1
            print(f"SKIP: {planned_out} (exists; use --overwrite)")
            continue

        if planned_out.exists() and bool(args.overwrite):
            try:
                planned_out.unlink()
            except FileNotFoundError:
                pass

        work.append(_WorkItem(input_ppt=input_ppt, output_pdf=planned_out))

    if not work:
        result = RunResult(processed=processed, succeeded=succeeded, failed=failed, skipped=skipped)
        print(
            f"Done. processed={result.processed} succeeded={result.succeeded} "
            f"failed={result.failed} skipped={result.skipped}",
            file=sys.stderr if result.failed else sys.stdout,
        )
        return 0

    # Group by output directory to preserve recursive folder structure.
    groups: dict[Path, list[_WorkItem]] = {}
    for item in work:
        groups.setdefault(item.output_pdf.parent, []).append(item)

    jobs = int(args.jobs)
    if jobs < 1:
        jobs = 1
    total = len(work)
    done = 0

    # Build tasks: (out_dir, items). Prefer 1 task per output dir, but split large
    # tasks until we have ~jobs tasks so multiple cores can be used even when all
    # inputs live in the same folder.
    tasks: list[tuple[Path, list[_WorkItem]]] = []
    for out_dir in sorted(groups.keys()):
        tasks.append((out_dir, sorted(groups[out_dir], key=lambda x: str(x.input_ppt))))

    while len(tasks) < jobs:
        # Split the largest task if it has more than 1 item.
        largest_idx = None
        largest_size = 1
        for idx, (_out, items) in enumerate(tasks):
            if len(items) > largest_size:
                largest_idx = idx
                largest_size = len(items)
        if largest_idx is None:
            break
        out_dir, items = tasks.pop(largest_idx)
        left, right = _split_evenly(items, 2)
        tasks.append((out_dir, left))
        tasks.append((out_dir, right))

    print(
        f"Converting {total} file(s) in {len(tasks)} task(s) with jobs={jobs} "
        f"(batching={'off' if bool(args.no_batch) else 'on'})..."
    )

    def _handle_results(results: list[tuple[str, str, bool, str | None]]) -> None:
        nonlocal done, succeeded, failed
        for inp_s, out_s, ok, err in results:
            done += 1
            if ok:
                succeeded += 1
                print(f"[{done}/{total}] OK: {inp_s} -> {out_s}")
            else:
                failed += 1
                msg = err or "unknown error"
                print(f"[{done}/{total}] FAIL: {inp_s}: {msg}", file=sys.stderr)

    if jobs == 1:
        for idx, (out_dir, items) in enumerate(tasks, start=1):
            print(f"Task {idx}/{len(tasks)}: {len(items)} file(s) -> {out_dir}")
            results = _worker_convert_group(
                soffice=soffice,
                pairs=[(str(it.input_ppt), str(it.output_pdf)) for it in items],
                out_dir=str(out_dir),
                timeout_s=timeout_s,
                no_batch=bool(args.no_batch),
            )
            _handle_results(results)
    else:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            future_to_task: dict[object, tuple[Path, int]] = {}
            for idx, (out_dir, items) in enumerate(tasks, start=1):
                print(f"Queued task {idx}/{len(tasks)}: {len(items)} file(s) -> {out_dir}")
                fut = ex.submit(
                    _worker_convert_group,
                    soffice=soffice,
                    pairs=[(str(it.input_ppt), str(it.output_pdf)) for it in items],
                    out_dir=str(out_dir),
                    timeout_s=timeout_s,
                    no_batch=bool(args.no_batch),
                )
                future_to_task[fut] = (out_dir, len(items))

            for fut in as_completed(future_to_task):
                out_dir, n_items = future_to_task[fut]
                try:
                    results = fut.result()
                except Exception as exc:
                    # Should be rare because worker catches most errors.
                    failed += n_items
                    done += n_items
                    print(f"FAIL: task for {out_dir} crashed: {exc}", file=sys.stderr)
                    continue
                _handle_results(results)

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
