#!/usr/bin/env python3
"""Invert colors for PDFs.

Robust approach: rasterize each page -> invert pixels -> rebuild a new PDF.
This works for essentially any PDF (vector, scanned, mixed, weird color spaces),
at the cost of losing selectable text and potentially increasing file size.

Default folders are relative to this script:
- input/:  place PDFs here
- output/: inverted PDFs written here

Output name: <input_name>_invert.pdf
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def _lazy_import_fitz():
    try:
        import fitz  # PyMuPDF

        return fitz
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: PyMuPDF (fitz). "
            "Install via one of: "
            "(1) make pdf_invert (auto-creates a venv and installs deps), "
            "(2) pip install pymupdf (inside a venv), "
            "(3) distro package e.g. sudo apt install python3-pymupdf"
        ) from exc


@dataclass(frozen=True)
class RunResult:
    processed: int
    succeeded: int
    failed: int


def _iter_input_pdfs(input_dir: Path) -> Iterable[Path]:
    if not input_dir.exists():
        return
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() == ".pdf":
            yield path


def _build_output_path(output_dir: Path, input_pdf: Path) -> Path:
    return output_dir / f"{input_pdf.stem}_invert.pdf"


def _clear_output_dir(output_dir: Path) -> None:
    """Remove existing files under output_dir (best-effort).

    To avoid surprising data loss, this only deletes PDF files.
    """

    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise NotADirectoryError(f"Output dir is not a directory: {output_dir}")

    for path in sorted(output_dir.rglob("*"), reverse=True):
        try:
            if path.is_file() and path.suffix.lower() == ".pdf":
                path.unlink()
            elif path.is_dir():
                # Clean up empty subfolders left behind.
                try:
                    path.rmdir()
                except OSError:
                    pass
        except Exception:
            # Best-effort cleanup; processing can still proceed.
            pass


def invert_pdf(
    *,
    input_pdf: Path,
    output_pdf: Path,
    dpi: int,
    password: str | None,
    overwrite: bool,
) -> None:
    fitz = _lazy_import_fitz()

    if output_pdf.exists() and not overwrite:
        raise FileExistsError(
            f"Output exists: {output_pdf}. Use --overwrite to replace it."
        )

    doc = fitz.open(input_pdf)
    try:
        if getattr(doc, "needs_pass", False):
            if not password:
                raise PermissionError(
                    f"{input_pdf.name} is password-protected. Provide --password."
                )
            ok = doc.authenticate(password)
            if not ok:
                raise PermissionError(
                    f"Wrong password for {input_pdf.name}."
                )

        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        out = fitz.open()
        try:
            # Preserve metadata when possible (best-effort)
            try:
                meta = dict(getattr(doc, "metadata", {}) or {})
                # Avoid confusing titles
                if meta.get("title"):
                    meta["title"] = f"{meta['title']} (inverted)"
                out.set_metadata(meta)
            except Exception:
                pass

            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                page_rect = page.rect

                # Force RGB; alpha off for smaller output and less ambiguity.
                pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)

                # Invert all pixels (in-place)
                try:
                    pix.invert_irect()
                except Exception:
                    # Fallback for older PyMuPDF versions
                    # Convert to bytes and invert via PIL if needed.
                    try:
                        from PIL import Image, ImageOps  # type: ignore
                    except Exception as exc:  # pragma: no cover
                        raise RuntimeError(
                            "This PyMuPDF version does not support Pixmap.invert_irect(). "
                            "Install Pillow for a fallback: sudo apt install python3-pil"
                        ) from exc

                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    img = ImageOps.invert(img)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    pix = fitz.Pixmap(buf.getvalue())

                out_page = out.new_page(width=page_rect.width, height=page_rect.height)
                out_page.insert_image(page_rect, pixmap=pix)

            # Save
            output_pdf.parent.mkdir(parents=True, exist_ok=True)
            out.save(
                output_pdf,
                garbage=4,
                deflate=True,
                clean=True,
            )
        finally:
            out.close()
    finally:
        doc.close()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent

    p = argparse.ArgumentParser(
        description="Invert all colors for PDFs in a folder (writes <name>_invert.pdf).",
    )
    p.add_argument(
        "--input-dir",
        type=Path,
        default=script_dir / "input",
        help="Folder containing PDFs to invert (default: ./input next to the script)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=script_dir / "output",
        help="Folder for inverted PDFs (default: ./output next to the script)",
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Render DPI before inversion (higher = sharper but slower/bigger) (default: 200)",
    )
    p.add_argument(
        "--password",
        type=str,
        default=None,
        help="Password for encrypted PDFs (if needed)",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output PDFs if they already exist",
    )
    p.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0 (useful for batch runs)",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = list(_iter_input_pdfs(input_dir))
    if not inputs:
        print(f"No PDFs found in: {input_dir}", file=sys.stderr)
        return 0

    # Start from a clean output folder for this batch.
    _clear_output_dir(output_dir)

    processed = 0
    succeeded = 0
    failed = 0

    for input_pdf in inputs:
        processed += 1
        output_pdf = _build_output_path(output_dir, input_pdf)

        try:
            invert_pdf(
                input_pdf=input_pdf,
                output_pdf=output_pdf,
                dpi=int(args.dpi),
                password=args.password,
                overwrite=bool(args.overwrite),
            )
            succeeded += 1
            print(f"OK  {input_pdf.name} -> {output_pdf.name}")
        except Exception as exc:
            failed += 1
            print(f"ERR {input_pdf.name}: {exc}", file=sys.stderr)

    result = RunResult(processed=processed, succeeded=succeeded, failed=failed)
    print(f"Done. processed={result.processed} ok={result.succeeded} failed={result.failed}")

    if args.exit_zero:
        return 0
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
