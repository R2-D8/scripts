#!/usr/bin/env python3
"""Invert PDF colors while preserving the original PDF structure.

Goal:
- Keep text as text (select/copy/search) and preserve vector graphics (lines,
    shapes, separators, etc.) by NOT rebuilding pages.

Approach (best-effort, structure-preserving):
- For each page, prepend a solid black background rectangle to its content.
- Rewrite the page content stream(s) in-place to invert color-setting operators
    used by text and vector graphics.
- By default, leave images unchanged.
- With --invert-images, invert images by setting /Decode arrays on image XObjects
    (so the image stream bytes are unchanged).

Limitations (expected):
- Some PDFs use patterns, ICCBased / DeviceN colorspaces, or inline images;
    these may not invert perfectly.
- Content streams are rewritten (whitespace/number formatting may change), but
    the page structure and objects are preserved.

Default folders are relative to this script:
- input/:  place PDFs here
- output/: inverted PDFs written here

Output name: <input_name>_inverted.pdf

Dependencies (repo-wide): PyMuPDF (fitz).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


def _lazy_import_fitz():
    try:
        import fitz  # PyMuPDF

        return fitz
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: PyMuPDF (fitz). Install via `make deps` "
            "(recommended) or `pip install pymupdf` inside a venv."
        ) from exc


_NUM_RE = re.compile(rb"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


@dataclass(frozen=True)
class RunResult:
    processed: int
    succeeded: int
    failed: int


def _iter_input_pdfs(input_dir: Path) -> Iterable[Path]:
    yield from _iter_input_pdfs_recursive(input_dir=input_dir, recursive=False)


def _iter_input_pdfs_recursive(*, input_dir: Path, recursive: bool) -> Iterable[Path]:
    if not input_dir.exists():
        return

    it = input_dir.rglob("*") if recursive else input_dir.iterdir()
    for path in sorted(it):
        if path.is_file() and path.suffix.lower() == ".pdf":
            yield path


def _build_output_path(*, output_dir: Path, input_dir: Path, input_pdf: Path) -> Path:
    rel = input_pdf.relative_to(input_dir)
    return output_dir / rel.parent / f"{rel.stem}_inverted.pdf"


def _clear_planned_outputs(*, output_dir: Path, input_dir: Path, inputs: Iterable[Path]) -> None:
    """Remove existing output files this run would generate (best-effort).

    IMPORTANT: Do not delete arbitrary PDFs under output_dir.
    This prevents accidental data loss when output_dir is a real folder that
    already contains user documents (and especially when output_dir == input_dir).
    """

    if output_dir.exists() and not output_dir.is_dir():
        raise NotADirectoryError(f"Output dir is not a directory: {output_dir}")

    for input_pdf in inputs:
        out = _build_output_path(output_dir=output_dir, input_dir=input_dir, input_pdf=input_pdf)
        try:
            if out.exists() and out.is_file():
                out.unlink()
        except Exception:
            # best-effort cleanup; processing can still proceed.
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


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _invert01(value: float) -> float:
    return 1.0 - _clamp01(value)


def _format_pdf_number(value: float) -> bytes:
    v = float(value)
    if abs(v) < 1e-12:
        v = 0.0
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    if s in ("", "-0"):
        s = "0"
    return s.encode("ascii")


def _is_number_token(token: bytes) -> bool:
    return bool(_NUM_RE.match(token))


def _iter_pdf_tokens(data: bytes) -> Iterator[bytes]:
    """Tokenize a PDF content stream.

    This is a conservative tokenizer for page content streams. It yields
    whitespace/comments as tokens too, so we can preserve most text unchanged.
    """

    i = 0
    n = len(data)

    def is_ws(b: int) -> bool:
        return b in (9, 10, 12, 13, 32)  # \t \n \f \r space

    def is_delim(b: int) -> bool:
        return b in b"()<>[]{}/%"

    while i < n:
        b = data[i]

        # Whitespace
        if is_ws(b):
            j = i + 1
            while j < n and is_ws(data[j]):
                j += 1
            yield data[i:j]
            i = j
            continue

        # Comments
        if b == 37:  # %
            j = i + 1
            while j < n and data[j] not in (10, 13):
                j += 1
            # include line break if present
            if j < n and data[j] in (10, 13):
                j += 1
                if j < n and data[j - 1] == 13 and data[j] == 10:
                    j += 1
            yield data[i:j]
            i = j
            continue

        # Literal strings: (...)
        if b == 40:  # (
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                c = data[j]
                if c == 92:  # backslash escape
                    j += 2
                    continue
                if c == 40:
                    depth += 1
                elif c == 41:
                    depth -= 1
                j += 1
            yield data[i:j]
            i = j
            continue

        # Hex strings or dict delimiters: <...> / << / >>
        if b == 60:  # <
            if i + 1 < n and data[i + 1] == 60:
                yield data[i : i + 2]
                i += 2
            else:
                j = i + 1
                while j < n and data[j] != 62:
                    j += 1
                j = min(n, j + 1)
                yield data[i:j]
                i = j
            continue

        if b == 62:  # >
            if i + 1 < n and data[i + 1] == 62:
                yield data[i : i + 2]
                i += 2
            else:
                yield data[i : i + 1]
                i += 1
            continue

        # Single-char delimiters
        if b in b"[]{}":
            yield data[i : i + 1]
            i += 1
            continue

        # Names: /Name
        if b == 47:  # /
            j = i + 1
            while j < n and not is_ws(data[j]) and not is_delim(data[j]):
                j += 1
            yield data[i:j]
            i = j
            continue

        # Regular token
        j = i + 1
        while j < n and not is_ws(data[j]) and not is_delim(data[j]):
            j += 1
        yield data[i:j]
        i = j


def _invert_page_content_stream(data: bytes) -> bytes:
    """Invert colors in a page content stream (text + vector graphics).

    Supported operators (best-effort):
    - DeviceGray: g / G
    - DeviceRGB: rg / RG
    - DeviceCMYK: k / K
    - Also handles sc / SC when the current color space is set to DeviceGray/RGB/CMYK.
    """

    out: list[bytes] = []
    pending: list[bytes] = []

    fill_cs: str | None = None
    stroke_cs: str | None = None

    def flush_with_operator(op: bytes) -> None:
        nonlocal pending
        out.extend(pending)
        out.append(op)
        pending = []

    def last_non_ws_tokens() -> list[bytes]:
        toks: list[bytes] = []
        for t in reversed(pending):
            if t and t[:1].isspace():
                continue
            if t.startswith(b"%"):
                continue
            toks.append(t)
        return toks

    def invert_last_numbers(count: int) -> None:
        # Find last `count` numeric tokens in pending and rewrite them.
        idxs: list[int] = []
        for idx in range(len(pending) - 1, -1, -1):
            t = pending[idx]
            if not t or t[:1].isspace() or t.startswith(b"%"):
                continue
            if _is_number_token(t):
                idxs.append(idx)
                if len(idxs) == count:
                    break
        if len(idxs) != count:
            return
        for idx in reversed(idxs):
            try:
                v = float(pending[idx].decode("ascii"))
            except Exception:
                return
            pending[idx] = _format_pdf_number(_invert01(v))

    # NOTE: inline images (BI ... ID ... EI) are not specially handled here.
    # Most modern PDFs use XObject images instead, which are unaffected.

    for tok in _iter_pdf_tokens(data):
        # Whitespace / delimiters are treated as operands in pending.
        stripped = tok.strip()
        if not stripped:
            pending.append(tok)
            continue

        # If token is an operator of interest, possibly rewrite pending then flush.
        if stripped in (b"rg", b"RG"):
            invert_last_numbers(3)
            if stripped == b"rg":
                fill_cs = "DeviceRGB"
            else:
                stroke_cs = "DeviceRGB"
            flush_with_operator(tok)
            continue

        if stripped in (b"g", b"G"):
            invert_last_numbers(1)
            if stripped == b"g":
                fill_cs = "DeviceGray"
            else:
                stroke_cs = "DeviceGray"
            flush_with_operator(tok)
            continue

        if stripped in (b"k", b"K"):
            invert_last_numbers(4)
            if stripped == b"k":
                fill_cs = "DeviceCMYK"
            else:
                stroke_cs = "DeviceCMYK"
            flush_with_operator(tok)
            continue

        if stripped == b"cs":
            # current fill colorspace, operand should be a name like /DeviceRGB
            toks = last_non_ws_tokens()
            if toks:
                name = toks[0]
                if name.startswith(b"/"):
                    fill_cs = name[1:].decode("latin-1", errors="ignore")
            flush_with_operator(tok)
            continue

        if stripped == b"CS":
            toks = last_non_ws_tokens()
            if toks:
                name = toks[0]
                if name.startswith(b"/"):
                    stroke_cs = name[1:].decode("latin-1", errors="ignore")
            flush_with_operator(tok)
            continue

        if stripped == b"sc":
            if fill_cs in ("DeviceRGB", "DeviceGray", "DeviceCMYK"):
                invert_last_numbers({"DeviceGray": 1, "DeviceRGB": 3, "DeviceCMYK": 4}[fill_cs])
            flush_with_operator(tok)
            continue

        if stripped == b"SC":
            if stroke_cs in ("DeviceRGB", "DeviceGray", "DeviceCMYK"):
                invert_last_numbers({"DeviceGray": 1, "DeviceRGB": 3, "DeviceCMYK": 4}[stroke_cs])
            flush_with_operator(tok)
            continue

        # Default: just accumulate.
        pending.append(tok)

    out.extend(pending)
    return b"".join(out)


def _background_stream_bytes(*, width: float, height: float) -> bytes:
    # Draw a black rectangle covering the full page. Use q/Q to keep state.
    # Coordinate system: (0,0) to (width,height) covers the page.
    w = _format_pdf_number(width)
    h = _format_pdf_number(height)
    return b"q\n0 0 0 rg\n0 0 " + w + b" " + h + b" re\nf\nQ\n"


def _parse_contents_xrefs(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, (list, tuple)):
        out: list[int] = []
        for v in value:
            if isinstance(v, int):
                out.append(v)
        return out
    return []


def _invert_images_by_decode(*, doc: Any, page: Any) -> None:
    """Invert images by setting /Decode arrays on image XObjects.

    This keeps image stream bytes unchanged (structure-friendly) and lets the
    PDF renderer invert samples.
    """

    for img in page.get_images(full=True):
        if not img:
            continue
        xref = int(img[0])

        try:
            if not doc.xref_is_image(xref):
                continue
        except Exception:
            continue

        # Skip image masks
        try:
            _, im_mask = doc.xref_get_key(xref, "ImageMask")
            if isinstance(im_mask, str) and im_mask.strip().lower() == "true":
                continue
        except Exception:
            pass

        # Determine number of components
        components: int | None = None
        try:
            _, cs = doc.xref_get_key(xref, "ColorSpace")
            if isinstance(cs, str):
                cs_s = cs.strip()
                if "DeviceRGB" in cs_s:
                    components = 3
                elif "DeviceGray" in cs_s:
                    components = 1
                elif "DeviceCMYK" in cs_s:
                    components = 4
        except Exception:
            components = None

        if components is None:
            continue

        # If /Decode exists, flip each pair. Otherwise set standard invert decode.
        try:
            _, decode_val = doc.xref_get_key(xref, "Decode")
        except Exception:
            decode_val = None

        decode_pairs: list[tuple[float, float]] = []
        if isinstance(decode_val, str) and decode_val.strip().startswith("["):
            # Extract floats from an array like: [0 1 0 1 0 1]
            nums = re.findall(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", decode_val)
            floats: list[float] = []
            for s in nums:
                try:
                    floats.append(float(s))
                except Exception:
                    pass
            if len(floats) >= 2 * components:
                for i in range(0, 2 * components, 2):
                    decode_pairs.append((floats[i], floats[i + 1]))

        if decode_pairs:
            flipped = []
            for a, b in decode_pairs[:components]:
                flipped.extend([b, a])
            decode_str = "[" + " ".join(_format_pdf_number(v).decode("ascii") for v in flipped) + "]"
        else:
            # Default invert for 0..1 samples: [1 0] repeated per component.
            decode_str = "[" + " ".join(["1 0"] * components) + "]"

        try:
            doc.xref_set_key(xref, "Decode", decode_str)
        except Exception:
            # best-effort
            pass


def invert_pdf_keep_text(
    *,
    input_pdf: Path,
    output_pdf: Path,
    password: str | None,
    overwrite: bool,
    invert_images: bool,
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
                raise PermissionError(f"Wrong password for {input_pdf.name}.")

        # Update metadata title best-effort.
        try:
            meta = dict(getattr(doc, "metadata", {}) or {})
            if meta.get("title"):
                meta["title"] = f"{meta['title']} (inverted keep-structure)"
            doc.set_metadata(meta)
        except Exception:
            pass

        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            rect = page.rect
            bg = _background_stream_bytes(width=rect.width, height=rect.height)

            contents_xrefs = _parse_contents_xrefs(page.get_contents())
            if not contents_xrefs:
                # Empty page: create a new content stream containing only the background.
                try:
                    xref = doc.get_new_xref()
                    doc.update_stream(xref, bg)
                    page.set_contents(xref)
                except Exception:
                    pass
            else:
                for idx, xref in enumerate(contents_xrefs):
                    try:
                        stream = doc.xref_stream(xref)
                        if not isinstance(stream, (bytes, bytearray)):
                            continue
                        inverted = _invert_page_content_stream(bytes(stream))
                        if idx == 0:
                            inverted = bg + inverted
                        doc.update_stream(xref, inverted)
                    except Exception:
                        # best-effort
                        continue

            if invert_images:
                _invert_images_by_decode(doc=doc, page=page)

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        # Preserve structure as much as possible: avoid garbage collection,
        # content cleaning, and recompression.
        doc.save(output_pdf, garbage=0, deflate=False, clean=False)
    finally:
        doc.close()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent

    p = argparse.ArgumentParser(
        description=(
            "Invert PDF colors while preserving text + vector structure (best-effort). "
            "(Images kept as-is by default.)"
        )
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
        "--recursive",
        action="store_true",
        help="Also process PDFs in subdirectories (preserves folder structure in output)",
    )
    p.add_argument(
        "--invert-images",
        action="store_true",
        help="Also invert images (default: keep images unchanged)",
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

    input_dir: Path = Path(args.input_dir).expanduser()
    output_dir: Path = Path(args.output_dir).expanduser()

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = list(_iter_input_pdfs_recursive(input_dir=input_dir, recursive=bool(args.recursive)))
    if not inputs:
        print(f"No PDFs found in: {input_dir}", file=sys.stderr)
        return 0

    # Start from a clean output set for this batch (only delete files we would generate).
    _clear_planned_outputs(output_dir=output_dir, input_dir=input_dir, inputs=inputs)

    processed = 0
    succeeded = 0
    failed = 0

    for input_pdf in inputs:
        processed += 1
        output_pdf = _build_output_path(output_dir=output_dir, input_dir=input_dir, input_pdf=input_pdf)

        try:
            invert_pdf_keep_text(
                input_pdf=input_pdf,
                output_pdf=output_pdf,
                password=args.password,
                overwrite=bool(args.overwrite),
                invert_images=bool(args.invert_images),
            )
            succeeded += 1
            try:
                in_rel = input_pdf.relative_to(input_dir)
                out_rel = output_pdf.relative_to(output_dir)
                print(f"OK  {in_rel} -> {out_rel}")
            except Exception:
                print(f"OK  {input_pdf.name} -> {output_pdf.name}")
        except Exception as exc:
            failed += 1
            try:
                in_rel = input_pdf.relative_to(input_dir)
                print(f"ERR {in_rel}: {exc}", file=sys.stderr)
            except Exception:
                print(f"ERR {input_pdf.name}: {exc}", file=sys.stderr)

    result = RunResult(processed=processed, succeeded=succeeded, failed=failed)
    print(
        f"Done. processed={result.processed} ok={result.succeeded} failed={result.failed}"
    )

    if args.exit_zero:
        return 0
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
