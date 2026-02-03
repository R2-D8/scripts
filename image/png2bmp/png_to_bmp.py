#!/usr/bin/env python3
"""Auto PNG <-> BMP converter.

This script is intentionally option-less: it looks for files in the sibling
folders next to this script and converts whatever it finds.

- PNGs found in ./pngs are converted to BMPs into ./bmps
- BMPs found in ./bmps are converted to PNGs into ./pngs

Sources are never deleted.

Channel preservation:
- If the input is 1-channel (grayscale), output is 1-channel.
- If the input is 3-channel (RGB), output is 3-channel.

Notes:
- If a PNG has transparency, it is flattened onto a white background (RGB).
- Existing outputs are only regenerated when the source is newer than the
    destination (or destination is missing).
"""

import sys
from pathlib import Path
from typing import List

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow (PIL) is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)


def is_png(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".png"


def is_bmp(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".bmp"


def flatten_if_alpha(img: Image.Image) -> Image.Image:
    """If image has alpha, flatten onto white background and return RGB."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background.convert("RGB")
    return img


def coerce_to_1_or_3_channels(img: Image.Image) -> Image.Image:
    """Return an image as either L (1 channel) or RGB (3 channels)."""
    img = flatten_if_alpha(img)

    if img.mode == "L":
        return img
    if img.mode == "RGB":
        return img

    # Some grayscale-like modes should remain 1-channel.
    if img.mode in ("1", "I", "F", "I;16"):
        return img.convert("L")

    # Palette / CMYK / etc -> RGB
    return img.convert("RGB")


def should_convert(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    try:
        return src.stat().st_mtime > dst.stat().st_mtime
    except OSError:
        return True


def convert_image(src: Path, dst: Path, dst_format: str) -> bool:
    """Convert a single image file (PNG or BMP) to the other format."""
    try:
        with Image.open(src) as img:
            img = coerce_to_1_or_3_channels(img)
            dst.parent.mkdir(parents=True, exist_ok=True)
            img.save(dst, format=dst_format)
        print(f"Converted: {src} -> {dst}")
        return True
    except Exception as e:
        print(f"Error converting {src}: {e}", file=sys.stderr)
        return False


def collect_pngs(folder: Path) -> List[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted([p for p in folder.glob("*.png") if is_png(p)])


def collect_bmps(folder: Path) -> List[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted([p for p in folder.glob("*.bmp") if is_bmp(p)])


def main(argv: List[str]) -> int:
    if argv:
        print("Note: arguments are ignored; auto mode is always used.")

    base_dir = Path(__file__).resolve().parent
    png_dir = base_dir / "pngs"
    bmp_dir = base_dir / "bmps"
    png_dir.mkdir(parents=True, exist_ok=True)
    bmp_dir.mkdir(parents=True, exist_ok=True)

    # Collect upfront to avoid converting files generated during this run.
    png_sources = collect_pngs(png_dir)
    bmp_sources = collect_bmps(bmp_dir)

    if not png_sources and not bmp_sources:
        print("No PNG or BMP files found to convert.")
        return 0

    ok = True

    # PNG -> BMP
    for src in png_sources:
        dst = bmp_dir / f"{src.stem}.bmp"
        if not should_convert(src, dst):
            continue
        if not convert_image(src, dst, dst_format="BMP"):
            ok = False

    # BMP -> PNG
    for src in bmp_sources:
        dst = png_dir / f"{src.stem}.png"
        if not should_convert(src, dst):
            continue
        if not convert_image(src, dst, dst_format="PNG"):
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
