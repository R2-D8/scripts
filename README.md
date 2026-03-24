# Overview

This repository is a grab-bag of small, standalone scripts (plus a `Makefile` for convenience) that I use for common tasks.

General layout:

- `image/`: image-related utilities (format conversion, generating downscaled variants, etc.)
- `pdf/`: PDF-related utilities
- `video/`: video-related utilities (downloading, format conversion, etc.)
- `other/`: unrelated utilities

Run everything via `make <target>` (recommended). Individual sections below document inputs/outputs and any extra dependencies.

For passing flags through to the underlying Python script, use a single standard variable:

```bash
make <target> ARGS="--some-flag --other-flag value"
```

# Flags summary

## Make variables

- `ARGS="..."`: extra CLI flags appended to the underlying script invocation.
- `N=<int>`: only for `subimages`; exponent for the default maximum denominator ($2^N$). Default is `N=6` ($2^6 = 64$) when you do not explicitly pass `--max-denom/--denoms/--min-denom`.

## Script flags (pass via `ARGS="..."`)

- `png2bmp` (image/png2bmp/png_to_bmp.py)
    - No flags. Any args are ignored (script always runs in auto mode).

- `subimages` (image/subimages/create_subimages.py)
    - `-i, --input, --input-dir PATH`: input image file or directory.
    - `-o, --output, --output-dir PATH`: output directory.
    - `-r, --recursive`: recurse into subdirectories.
    - `--exit-zero`: always exit 0.
    - `--max-denom INT`: max denominator (must be a power of two; default is 64 if not set).
    - `--min-denom INT`: min power-of-two denominator when using `--max-denom` (default 2).
    - `--denoms CSV`: explicit denominators like `2,4,8,16` (mutually exclusive with `--max-denom`).

- `video_downloader` (video/video_downloader/video_downloader.py)
    - `-i, --input, --input-dir PATH`: input text file.
    - `-o, --output, --output-dir PATH`: output directory.
    - `-f, --format STR`: yt-dlp format selector.
    - `--merge-output-format STR`: force a container via yt-dlp `--merge-output-format`.
    - `--fail-fast`: stop immediately on first download error.
    - `--verbose`: show full yt-dlp logs.
    - `--report PATH`: write run report to this file.
    - `--exit-zero`: always exit 0 even if some downloads fail.
    - `--clear`: clear output directory before downloading.

- `transcribe_media` (video/transcribe_media/transcribe_media.py)
    - `-i, --input-dir PATH`: input folder containing media files.
    - `-o, --output-dir PATH`: output folder for per-file `.txt` transcripts.
    - `-r, --recursive`: include subdirectories (preserves structure under output).
    - `-l, --language {it,en}`: language model to use (default: `it`).
    - `--start TS`: start timestamp for the segment to transcribe (e.g. `12.5`, `01:23`, `00:01:23.500`).
    - `--end TS`: end timestamp for the segment to transcribe.

- `invert_colors` (pdf/invert_colors/invert_colors.py)
    - `-i, --input, --input-dir PATH`: input folder.
    - `-o, --output, --output-dir PATH`: output folder.
    - `-r, --recursive`: include PDFs/images in subdirectories (preserves structure under output).
    - `--dpi INT`: render DPI before inversion for PDFs (ignored for images).
    - `--password STR`: password for encrypted PDFs.
    - `--overwrite`: overwrite outputs if they already exist.
    - `--exit-zero`: always exit 0 (batch mode).

- `pdf_invert_keep_text` (pdf/invert_colors_keep_text/invert_pdf_colors_keep_text.py)
    - `-i, --input, --input-dir PATH`: input folder.
    - `-o, --output, --output-dir PATH`: output folder.
    - `-r, --recursive`: include PDFs in subdirectories (preserves structure under output).
    - `--invert-images`: also invert embedded images (default is to keep images unchanged).
    - `--password STR`: password for encrypted PDFs.
    - `--overwrite`: overwrite output PDFs if they already exist.
    - `-j, --jobs INT`: parallel jobs (default: physical CPU cores).
    - `--exit-zero`: always exit 0 (batch mode).

- `ppt_to_pdf` (pdf/ppt_to_pdf/ppt_to_pdf.py)
    - `-i, --input, --input-dir PATH`: input folder.
    - `-o, --output, --output-dir PATH`: output folder.
    - `-r, --recursive`: include presentations in subdirectories (preserves structure under output).
    - `-j, --jobs INT`: parallel LibreOffice jobs (default: physical CPU cores).
    - `--overwrite`: overwrite output PDFs if they already exist.
    - `--soffice PATH|NAME`: explicit `soffice` path/name (default: search `PATH`).
    - `--timeout SECONDS`: per-file timeout (`0` = no timeout).
    - `--exit-zero`: always exit 0 (batch mode).

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

# PDF/Image (Invert Colors)

There are two color-inversion scripts:

1. **Robust (PDF+image)**: handles both PDFs and common image formats. PDFs are rasterized and become _flattened_ (no selectable text).
2. **Keep text selectable (best-effort)**: tries to preserve text as text (select/copy/search), but is less reliable and may not preserve vector graphics.

Install dependencies via the repo venv (recommended): `make deps`

## Robust inverter (flattened)

This script inverts both PDFs and common image files. PDFs are rasterized page-by-page and rebuilt as flattened PDFs; images are inverted directly with Pillow.

Put PDFs/images into `pdf/invert_colors/input/` and run:

```bash
make invert_colors
```

Outputs are written to `pdf/invert_colors/output/` as:

- `<input_name>_inverted.pdf`
- `<input_name>_inverted<ext>` for images

Useful options:

```bash
# control quality/size
make invert_colors ARGS="--dpi 150"

# encrypted PDFs
make invert_colors ARGS="--password 'your-password'"

# overwrite existing outputs
make invert_colors ARGS="--overwrite"

# include files in subdirectories (keeps the same subdir structure under output/)
make invert_colors ARGS="--recursive"

# custom input/output locations
make invert_colors ARGS="-i /abs/path/in -o /abs/path/out"


# or via flags (passed through)
make invert_colors ARGS="--input-dir /abs/path/in --output-dir /abs/path/out --overwrite"
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
make pdf_invert_keep_text ARGS="--invert-images"

# encrypted PDFs
make pdf_invert_keep_text ARGS="--password 'your-password'"

# overwrite existing outputs
make pdf_invert_keep_text ARGS="--overwrite"

# include PDFs in subdirectories (keeps the same subdir structure under output/)
make pdf_invert_keep_text ARGS="--recursive"

# control parallelism (optional; default: physical CPU cores)
make pdf_invert_keep_text ARGS="-j 4"

# custom input/output locations
make pdf_invert_keep_text ARGS="-i /abs/path/in -o /abs/path/out"

# or via long flags
make pdf_invert_keep_text ARGS="--input-dir /abs/path/in --output-dir /abs/path/out --overwrite"
```

Limitations (expected): some PDFs use advanced color spaces (patterns / ICCBased / DeviceN) or inline images; those may not invert perfectly.

# PPT/PPTX -> PDF

Convert PowerPoint presentations (`.ppt` / `.pptx`) to PDFs using LibreOffice in headless mode.

Prerequisite: LibreOffice installed and `soffice` available on your `PATH`.

On Debian/Ubuntu:

```bash
sudo apt install libreoffice
```

Put presentations into `pdf/ppt_to_pdf/input/` and run:

```bash
make ppt_to_pdf
```

Outputs are written to `pdf/ppt_to_pdf/output/` as:

- `<input_stem>.pdf`

Useful options:

```bash
# include subfolders (preserves structure under output/)
make ppt_to_pdf ARGS="--recursive"

# overwrite existing PDFs
make ppt_to_pdf ARGS="--overwrite"

# control parallelism (optional; default: physical CPU cores)
# (Makefile passes this through to --jobs)
make ppt_to_pdf PPT_TO_PDF_JOBS=4

# custom input/output locations
make ppt_to_pdf ARGS="-i /abs/path/in -o /abs/path/out"

# or pass flags through
make ppt_to_pdf ARGS="--input-dir /abs/path/in --output-dir /abs/path/out --overwrite"
```

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
make subimages ARGS="-i /abs/path/in -o /abs/path/out"

# control parallelism (optional; default: physical CPU cores)
make subimages ARGS="-j 4"

# relative paths are fine too (relative to the repo root when using make)
make subimages ARGS="-i ./my_images -o ./out_subimages"
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
make subimages ARGS="--max-denom 256"

# generate only specific scales
make subimages ARGS="--denoms 2,8,64"
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
make video_downloader ARGS="--clear"
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

# Media Transcription

Transcribe a directory of media files (mix of `.mp3`, `.mp4`, `.avi`) into per-file `.txt` transcripts.

Put media into `video/transcribe_media/input/` and run:

```bash
make transcribe_media
```

Outputs are written to `video/transcribe_media/output/` as:

- `<input_stem>.txt`

If you include subdirectories and pass `--recursive`, the output directory mirrors the input folder structure.

Useful options:

```bash
# include subfolders (preserves structure under output/)
make transcribe_media ARGS="--recursive"

# switch to English model
make transcribe_media ARGS="--language en"

# transcribe only a segment
make transcribe_media ARGS="--start 00:01:00 --end 00:02:30"

# custom input/output locations
make transcribe_media ARGS="-i /abs/path/in -o /abs/path/out"
```

Notes:

- This uses repo-local `ffmpeg` (installed by `make bootstrap`).
- On first run it downloads a Vosk language model into `video/transcribe_media/model/` (Italian by default).

## input.txt (optional)

If an `input.txt` file is present in the input folder (and, when using `--recursive`, in any subfolder), it can contain:

- URLs (lines starting with `http://` or `https://`) to download via the existing downloader, and then transcribe.
- File references (the **filename without extension**, optionally as a relative path like `subdir/name`) to apply per-file start/end timestamps to existing local media.

Per-entry timestamps:

- The line **immediately after** a URL or file reference can contain `START END` timestamps (examples: `01:23 02:10`, `00:01:23.500 00:02:00`, `12.5 20`).
- You can use `-` to mean “unset” (examples: `00:30 -`, `- 02:00`) and you can also provide just one value (treated as `START`).
- If a file reference matches multiple files (e.g. both `name.mp3` and `name.mp4` exist), the same segment is applied to all matches.
- If a file reference does not match anything, it is ignored (not all lines are necessarily file references).
- Not all media files need to be listed in `input.txt`: any discovered `.mp3/.mp4/.avi` will still be transcribed; `input.txt` only adds downloads and/or overrides timestamps.
- If there is no per-entry segment, `--start/--end` are used as defaults; if those are also unset, the full file is transcribed.

Downloader output:

- Downloads are written under `<output-dir>/downloads/` (default: `video/transcribe_media/output/downloads/`).
- With `--recursive`, each subfolder `input.txt` downloads into `<output-dir>/downloads/<that_subfolder>/`.
