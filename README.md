# Overview

This repository is a grab-bag of small, standalone scripts (plus a `Makefile` for convenience) that I use for common tasks.

General layout:

- `image/`: image-related utilities (format conversion, generating downscaled variants, etc.)
- `pdf/`: PDF-related utilities
- `video/`: video-related utilities (downloading, format conversion, etc.)
- `other/`: unrelated utilities

Run everything via `make <target>` (recommended). Individual sections below document inputs/outputs and any extra dependencies.

# Python environment (repo-wide)

Manual prerequisites on a fresh machine:

- Python 3
- Python `venv` support (e.g. `python3-venv` on Debian/Ubuntu)

Then bootstrap everything else (no sudo installs required):

```bash
make bootstrap
```

Bootstrapping creates a repo-wide virtualenv at `.venv/`, installs every Python package needed by any script, and downloads a local static `ffmpeg` into `tools/ffmpeg/`.

All `make <target>` commands automatically use `.venv/bin/python` (and also find venv-installed console tools like `yt-dlp`) without requiring manual activation.

Notes:

- You still need an internet connection the first time you bootstrap (downloads Python packages + ffmpeg).
- The downloaded ffmpeg build is a static GPLv3 build (see `tools/ffmpeg/SOURCE.txt`).

# PDF (Invert Colors)

There are two PDF color-inversion scripts:

1. **Robust (rasterize pages)**: works on almost any PDF, but the result is _flattened_ (no selectable text).
2. **Keep text selectable (best-effort)**: tries to preserve text as text (select/copy/search), but is less reliable and may not preserve vector graphics.

Install dependencies via the repo venv (recommended): `make deps`

## Robust inverter (flattened)

This script rasterizes each page to an image, inverts pixels, then rebuilds a new PDF. This works for essentially any PDF, but the output will be a flattened PDF (no selectable text / vector shapes), and file size depends on the chosen DPI.

Put PDFs into `pdf/invert_colors/input/` and run:

```bash
make pdf_invert
```

Outputs are written to `pdf/invert_colors/output/` as:

- `<input_name>_inverted.pdf`

Useful options:

```bash
# control quality/size
make pdf_invert PDF_ARGS="--dpi 150"

# encrypted PDFs
make pdf_invert PDF_ARGS="--password 'your-password'"

# overwrite existing outputs
make pdf_invert PDF_ARGS="--overwrite"

# include PDFs in subdirectories (keeps the same subdir structure under output/)
make pdf_invert PDF_ARGS="--recursive"

# custom input/output locations
make pdf_invert INPUT_DIR="/abs/path/in" OUTPUT_DIR="/abs/path/out"

# or via flags (passed through)
make pdf_invert PDF_ARGS="--input-dir /abs/path/in --output-dir /abs/path/out --overwrite"
```

## Keep-text inverter (best-effort)

This script tries to keep the PDF structure intact: it prepends a black background to each page and rewrites the existing page content streams to invert color-setting operators (text + vector graphics). That means things like page divider lines and bold/italic text should remain, because the original drawing/text commands are still there.

By default it **keeps images unchanged**. If you want images inverted too, pass `--invert-images` (it uses PDF `/Decode` arrays when possible).

Put PDFs into `pdf/invert_colors_keep_text/input/` and run:

```bash
make pdf_invert_keep_text
```

Outputs are written to `pdf/invert_colors_keep_text/output/` as:

- `<input_name>_inverted.pdf`

Useful options:

```bash
# also invert embedded images
make pdf_invert_keep_text PDF_KT_ARGS="--invert-images"

# encrypted PDFs
make pdf_invert_keep_text PDF_KT_ARGS="--password 'your-password'"

# overwrite existing outputs
make pdf_invert_keep_text PDF_KT_ARGS="--overwrite"

# include PDFs in subdirectories (keeps the same subdir structure under output/)
make pdf_invert_keep_text PDF_KT_ARGS="--recursive"

# custom input/output locations
make pdf_invert_keep_text \
    INPUT_DIR="/abs/path/in" \
    OUTPUT_DIR="/abs/path/out"

# or via flags (passed through)
make pdf_invert_keep_text PDF_KT_ARGS="--input-dir /abs/path/in --output-dir /abs/path/out"
```

Limitations (expected): some PDFs use advanced color spaces (patterns / ICCBased / DeviceN) or inline images; those may not invert perfectly.

# PNG <-> BMP

Dump PNG files into `image/png2bmp/pngs` and/or BMP files into `image/png2bmp/bmps`, then run:

```bash
make png2bmp
```

This auto-converts both ways:

- PNGs in `image/png2bmp/pngs` -> BMPs in `image/png2bmp/bmps`
- BMPs in `image/png2bmp/bmps` -> PNGs in `image/png2bmp/pngs`

It never deletes the source files.

Requires Pillow (installed via `make bootstrap` / `make deps`).

# Subimages (Downscale)

Put `.png` or `.bmp` images into `image/subimages/input` and run:

```bash
make subimages
```

To use custom input/output directories:

```bash
make subimages INPUT_DIR="/abs/path/in" OUTPUT_DIR="/abs/path/out"

# relative paths are fine too (relative to the repo root when using make)
make subimages INPUT_DIR="./my_images" OUTPUT_DIR="./out_subimages"
```

To change how far it goes (generate up to $1/2^N$):

```bash
# up to 1/32 (2^5)
make subimages N=5
```

This generates resized copies at 1/2, 1/4, 1/8, ... up to 1/64 into `image/subimages/output`, preserving any subfolder structure.

Output files are written directly into `image/subimages/output` (no scale subfolders) and are named like `1_2_<original_name>`, `1_4_<original_name>`, etc. The output folder is wiped at the start of each run.

Customize the scale set:

```bash
# generate 1/2..1/256
make subimages SUBIMAGES_ARGS="--max-denom 256"

# generate only specific scales
make subimages SUBIMAGES_ARGS="--denoms 2,8,64"
```

# Video Downloader

Downloads videos listed in a text file and writes them into `video/video_downloader/output/`.

Run:

```bash
make video_downloader
```

Extra options:

```bash
# clear output/ before downloading
make video_downloader VIDEO_DOWNLOADER_ARGS="--clear"
```

This target runs in “batch mode” (it won’t fail the whole `make` if a few links fail). See the report file for details.

By default, the downloader **does not** clear the output folder; it appends new downloads into `video/video_downloader/output/` and auto-suffixes names if needed.
If you want each run to start fresh, run the script directly with `--clear`.

## Input format

Edit `video/video_downloader/input.txt`.

- Any line that is a link (starts with `http://` or `https://`) is treated as a URL to download.
- Filenames are generated as:
    - `<title>_<stripped_url>___<timestamp>` when both are present
    - `<title>_<stripped_url>` when only a valid title is present
    - `<stripped_url>___<timestamp>` when only a valid timestamp is present
    - `<stripped_url>` when neither is present
- `title` is the previous non-comment line **only if** it is not a URL and does not contain `:`.
- A blank line breaks the “title applies to next URL” association (so titles don’t carry across sections), and consecutive URLs will not reuse a previous title.
- `timestamp` is the first meaningful line immediately after the URL **only if** it contains `:` and is not a URL (e.g. `01:27`).
- `stripped_url` is the URL with `http://` / `https://` removed and `/` replaced with `_`.
- Any characters not suitable for filenames are replaced with `_`.
- Comment lines are ignored if they start with `#` or `//`.

Example:

```text
My first video
https://www.youtube.com/watch?v=xxxxxxxxxxx

// junk lines are fine
Some note that will become the name for the next link
https://youtu.be/yyyyyyyyyyy
```

## Output format

By default the script prefers `.mp4`; if it can’t produce mp4, it falls back to `.avi`.

A report is written to `video/video_downloader/output.txt` with per-link success/failure details (it updates as the run progresses).

This merge step requires `ffmpeg`, which is handled by `make bootstrap` (downloads a local static build into `tools/ffmpeg/`).

### Windows (single self-contained .exe)

If you want to run this on a Windows host with **no Python/yt-dlp/ffmpeg installs**, you can build a single-file executable using PyInstaller.

- Build on Windows: run [video/video_downloader/packaging/windows/build_onefile.cmd](video/video_downloader/packaging/windows/build_onefile.cmd)
- Output: `video/video_downloader/dist/video_downloader.exe`
- Usage: put an `input.txt` next to the `.exe` (same format as described above); it will create `output/` and `output.txt` next to the `.exe`.

Note: PyInstaller onefile executables unpack embedded binaries to a temporary folder at runtime, but everything is shipped inside the `.exe`.
