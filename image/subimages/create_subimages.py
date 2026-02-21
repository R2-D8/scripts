#!/usr/bin/env python3
"""Subimage generator (downscaled copies)

Creates resized copies of all images in an input directory at fractional scales:
1/2, 1/4, 1/8, ... by default up to 1/64.

Supported input/output formats: PNG and BMP (based on file extension).

Default layout:
    subimages/input   (source images)
    subimages/output  (generated images)

Usage:
    python3 subimages/create_subimages.py
    python3 subimages/create_subimages.py -i subimages/input -o subimages/output
    python3 subimages/create_subimages.py --input-dir /path/to/input --output-dir /path/to/output
    python3 subimages/create_subimages.py -i subimages/input -r --max-denom 256

Notes:
- Output keeps the same extension as the source.
- When saving BMP, images with alpha are flattened onto white.
- Output is written flat into the output directory with names like: 1_2_<original_name>.
- If input is recursive and duplicate names exist, the relative path is encoded into the filename.
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

try:
    from PIL import Image
except ImportError:
    print(
        "Error: Pillow (PIL) is required. Install with: sudo apt install python3-pil (or pip install Pillow)",
        file=sys.stderr,
    )
    sys.exit(1)


SUPPORTED_EXTS = {".png", ".bmp"}


def is_supported_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTS


def flatten_if_alpha_for_bmp(img: Image.Image) -> Image.Image:
    """BMP doesn't support alpha; flatten onto white if needed."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background.convert("RGB")
    if img.mode == "P":
        return img.convert("RGB")
    return img


def collect_images(root: Path, recursive: bool) -> List[Path]:
    if root.is_file():
        return [root] if is_supported_image(root) else []

    if not root.is_dir():
        return []

    if recursive:
        candidates: Iterable[Path] = root.rglob("*")
    else:
        candidates = root.glob("*")

    return [p for p in candidates if is_supported_image(p)]


def is_power_of_two(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def denoms_from_range(min_denom: int, max_denom: int) -> List[int]:
    if min_denom < 2:
        raise ValueError("min denominator must be >= 2")
    if max_denom < min_denom:
        raise ValueError("max denominator must be >= min denominator")
    if not is_power_of_two(min_denom) or not is_power_of_two(max_denom):
        raise ValueError("min/max denominators must be powers of two")

    denoms: List[int] = []
    denom = min_denom
    while denom <= max_denom:
        denoms.append(denom)
        denom *= 2
    return denoms


def parse_denoms_csv(text: str) -> List[int]:
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        raise ValueError("--denoms must not be empty")

    denoms: List[int] = []
    for part in parts:
        try:
            denom = int(part)
        except ValueError as e:
            raise ValueError(f"Invalid denominator: {part!r}") from e
        if denom < 2 or not is_power_of_two(denom):
            raise ValueError(f"Denominator must be power-of-two and >= 2: {denom}")
        denoms.append(denom)

    return sorted(set(denoms))


def safe_rel_filename(src: Path, input_root: Path) -> str:
    """Create a stable, filesystem-safe name for src under input_root.

    - For directory input, encode the relative path to avoid collisions.
    - Keep the extension.
    """
    if input_root.is_dir():
        rel = src.relative_to(input_root).as_posix()
        # Flatten subdirs into filename to avoid creating output subdirectories.
        rel = rel.replace("/", "__")
        return rel
    return src.name


def resized_size(width: int, height: int, denom: int) -> tuple[int, int]:
    # Use rounding to reduce bias; clamp to at least 1px.
    new_w = max(1, int(round(width / denom)))
    new_h = max(1, int(round(height / denom)))
    return new_w, new_h


def save_resized(src: Path, dst: Path, denom: int) -> tuple[int, int]:
    with Image.open(src) as img:
        src_mode = img.mode
        target_size = resized_size(img.width, img.height, denom)

        # Pillow 9+: Image.Resampling exists. Fallback for older versions.
        resample = getattr(Image, "Resampling", Image).LANCZOS
        resized = img.resize(target_size, resample=resample)

        # Preserve channel layout where possible:
        # - If the source is 1-channel (e.g. 'L'), keep it 1-channel.
        # - If the source is 3-channel ('RGB'), keep it 3-channel.
        # We only change mode when required by the output format (e.g. BMP + alpha).
        if resized.mode != src_mode and resized.mode in ("RGB", "L") and src_mode in ("RGB", "L"):
            resized = resized.convert(src_mode)

        if dst.suffix.lower() == ".bmp":
            resized = flatten_if_alpha_for_bmp(resized)
            dst.parent.mkdir(parents=True, exist_ok=True)
            resized.save(dst, format="BMP")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            resized.save(dst, format="PNG")

        return target_size


def output_path_for(src: Path, input_root: Path, output_root: Path, denom: int) -> Path:
    base_name = safe_rel_filename(src, input_root)
    return output_root / f"1_{denom}_{base_name}"


def is_relative_to(path: Path, possible_parent: Path) -> bool:
    try:
        path.relative_to(possible_parent)
        return True
    except Exception:
        return False


def clean_output_dir(output_root: Path, input_path: Path) -> None:
    resolved_out = output_root.resolve()

    if resolved_out == Path("/"):
        raise ValueError("Refusing to wipe '/'")
    if resolved_out == Path.home().resolve():
        raise ValueError("Refusing to wipe your home directory")
    if resolved_out == Path.cwd().resolve():
        raise ValueError("Refusing to wipe the current working directory")

    if input_path.exists() and input_path.is_dir():
        resolved_in = input_path.resolve()
        if resolved_out == resolved_in:
            raise ValueError("Output directory cannot be the same as input directory")
        if is_relative_to(resolved_out, resolved_in):
            raise ValueError("Refusing to wipe an output directory inside the input directory")

    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {output_root}")

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def main(argv: Sequence[str]) -> int:
    script_dir = Path(__file__).resolve().parent
    default_input = script_dir / "input"
    default_output = script_dir / "output"

    parser = argparse.ArgumentParser(description="Create downscaled copies of PNG/BMP images (1/2, 1/4, ...).")
    parser.add_argument(
        "-i",
        "--input",
        "--input-dir",
        dest="input",
        type=Path,
        default=default_input,
        help="Input image file or directory (default: ./input next to the script)",
    )
    parser.add_argument(
        "-o",
        "--output",
        "--output-dir",
        type=Path,
        dest="output",
        default=default_output,
        help="Output directory (default: ./output next to the script)",
    )
    parser.add_argument("-r", "--recursive", action="store_true", help="Recurse into subdirectories")

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--max-denom",
        type=int,
        default=64,
        help="Max power-of-two denominator (default: 64 -> creates 1/2..1/64)",
    )
    group.add_argument(
        "--denoms",
        type=str,
        default=None,
        help="Comma-separated denominators, e.g. 2,4,8,16 (powers of two only)",
    )

    parser.add_argument(
        "--min-denom",
        type=int,
        default=2,
        help="Min power-of-two denominator when using --max-denom (default: 2)",
    )

    args = parser.parse_args(list(argv))

    input_path: Path = args.input
    output_root: Path = args.output

    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        print(f"Hint: put images into: {default_input}")
        return 2

    try:
        if args.denoms is not None:
            denoms = parse_denoms_csv(args.denoms)
        else:
            denoms = denoms_from_range(args.min_denom, args.max_denom)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    try:
        clean_output_dir(output_root, input_path)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    images = collect_images(input_path, args.recursive)
    if not images:
        print("No .png or .bmp files found.")
        return 0

    ok = True
    for src in images:
        for denom in denoms:
            dst = output_path_for(src, input_path, output_root, denom)
            try:
                target_size = save_resized(src, dst, denom)
                print(f"Wrote: {dst}")
                if target_size == (1, 1):
                    break
            except Exception as e:
                ok = False
                print(f"Error processing {src} at 1/{denom}: {e}", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
