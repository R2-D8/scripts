#!/usr/bin/env python3
"""Invert colors for PDFs and image files.

PDFs use a robust approach: rasterize each page -> invert pixels -> rebuild a new
PDF. This works for essentially any PDF (vector, scanned, mixed, weird color
spaces), at the cost of losing selectable text and potentially increasing file
size.

Images are inverted with Pillow while preserving alpha channels.

Default folders are relative to this script:
- input/:  place PDFs/images here
- output/: inverted files written here

Output names:
- PDFs:   <input_name>_inverted.pdf
- Images: <input_name>_inverted<ext>
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}
SUPPORTED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES


def _lazy_import_fitz():
    try:
        import fitz  # PyMuPDF

        return fitz
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: PyMuPDF (fitz). "
            "Install via one of: "
            "(1) make invert_colors (auto-creates a venv and installs deps), "
            "(2) pip install pymupdf (inside a venv), "
            "(3) distro package e.g. sudo apt install python3-pymupdf"
        ) from exc


def _lazy_import_pillow():
    try:
        from PIL import Image, ImageOps

        return Image, ImageOps
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: Pillow. "
            "Install via one of: "
            "(1) make invert_colors (auto-creates a venv and installs deps), "
            "(2) pip install pillow (inside a venv), "
            "(3) distro package e.g. sudo apt install python3-pil"
        ) from exc


@dataclass(frozen=True)
class RunResult:
    processed: int
    succeeded: int
    failed: int


def _iter_supported_inputs(*, input_dir: Path, recursive: bool) -> Iterable[Path]:
    if not input_dir.exists():
        return

    it = input_dir.rglob("*") if recursive else input_dir.iterdir()
    for path in sorted(it):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path


def _build_output_path(*, output_dir: Path, input_dir: Path, input_path: Path) -> Path:
    rel = input_path.relative_to(input_dir)
    suffix = input_path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return output_dir / rel.parent / f"{rel.stem}_inverted.pdf"
    return output_dir / rel.parent / f"{rel.stem}_inverted{suffix}"


def _clear_planned_outputs(*, output_dir: Path, input_dir: Path, inputs: Iterable[Path]) -> None:
    """Remove existing output files this run would generate (best-effort).

    IMPORTANT: Do not delete arbitrary files under output_dir.
    This prevents accidental data loss when output_dir is a real folder that
    already contains user documents (and especially when output_dir == input_dir).
    """

    if output_dir.exists() and not output_dir.is_dir():
        raise NotADirectoryError(f"Output dir is not a directory: {output_dir}")

    for input_path in inputs:
        out = _build_output_path(output_dir=output_dir, input_dir=input_dir, input_path=input_path)
        try:
            if out.exists() and out.is_file():
                out.unlink()
        except Exception:
            # Best-effort cleanup; processing can still proceed.
            pass

    # Best-effort: remove empty subfolders under output_dir.
    if not output_dir.exists():
        return
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
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


def _invert_pil_image(image):
    Image, ImageOps = _lazy_import_pillow()

    # Preserve alpha channel while inverting only visible color channels.
    if image.mode == "RGBA":
        r, g, b, a = image.split()
        rgb = Image.merge("RGB", (r, g, b))
        inv_rgb = ImageOps.invert(rgb)
        ir, ig, ib = inv_rgb.split()
        return Image.merge("RGBA", (ir, ig, ib, a))

    if image.mode == "LA":
        l, a = image.split()
        inv_l = ImageOps.invert(l)
        return Image.merge("LA", (inv_l, a))

    if image.mode == "P":
        if "transparency" in image.info:
            return _invert_pil_image(image.convert("RGBA"))
        return _invert_pil_image(image.convert("RGB"))

    if image.mode == "1":
        image = image.convert("L")

    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")

    return ImageOps.invert(image)


def invert_image(*, input_image: Path, output_image: Path, overwrite: bool) -> None:
    Image, _ = _lazy_import_pillow()

    if output_image.exists() and not overwrite:
        raise FileExistsError(
            f"Output exists: {output_image}. Use --overwrite to replace it."
        )

    with Image.open(input_image) as image:
        inverted = _invert_pil_image(image)
        output_image.parent.mkdir(parents=True, exist_ok=True)
        inverted.save(output_image)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent

    p = argparse.ArgumentParser(
        description=(
            "Invert colors for PDFs and images in a folder "
            "(writes <name>_inverted.*)."
        ),
    )
    p.add_argument(
        "-i",
        "--input",
        "--input-dir",
        dest="input_dir",
        type=Path,
        default=script_dir / "input",
        help="Folder containing PDFs/images to invert (default: ./input next to the script)",
    )
    p.add_argument(
        "-o",
        "--output",
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=script_dir / "output",
        help="Folder for inverted files (default: ./output next to the script)",
    )
    p.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help=(
            "Also process files in subdirectories "
            "(preserves folder structure in output)"
        ),
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Render DPI for PDFs (ignored for images) (default: 200)",
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
        help="Overwrite output files if they already exist",
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

    inputs = list(_iter_supported_inputs(input_dir=input_dir, recursive=bool(args.recursive)))
    if not inputs:
        suffixes = ", ".join(sorted(SUPPORTED_SUFFIXES))
        print(f"No supported files found in: {input_dir} (supported: {suffixes})", file=sys.stderr)
        return 0

    # Start from a clean output set for this batch (only delete files we would generate).
    _clear_planned_outputs(output_dir=output_dir, input_dir=input_dir, inputs=inputs)

    processed = 0
    succeeded = 0
    failed = 0

    def _process_one(input_path: Path) -> tuple[Path, Path]:
        output_path = _build_output_path(output_dir=output_dir, input_dir=input_dir, input_path=input_path)
        if input_path.suffix.lower() in PDF_SUFFIXES:
            invert_pdf(
                input_pdf=input_path,
                output_pdf=output_path,
                dpi=int(args.dpi),
                password=args.password,
                overwrite=bool(args.overwrite),
            )
        else:
            invert_image(
                input_image=input_path,
                output_image=output_path,
                overwrite=bool(args.overwrite),
            )
        return input_path, output_path

    processed = len(inputs)

    try:
        for input_path in inputs:
            try:
                _in, _out = _process_one(input_path)
                succeeded += 1
                try:
                    in_rel = _in.relative_to(input_dir)
                    out_rel = _out.relative_to(output_dir)
                    print(f"OK  {in_rel} -> {out_rel}")
                except Exception:
                    print(f"OK  {_in.name} -> {_out.name}")
            except Exception as exc:
                failed += 1
                try:
                    in_rel = input_path.relative_to(input_dir)
                    print(f"ERR {in_rel}: {exc}", file=sys.stderr)
                except Exception:
                    print(f"ERR {input_path.name}: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 0 if bool(args.exit_zero) else 130

    result = RunResult(processed=processed, succeeded=succeeded, failed=failed)
    print(f"Done. processed={result.processed} ok={result.succeeded} failed={result.failed}")

    if args.exit_zero:
        return 0
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
