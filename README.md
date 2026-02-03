# Overview

This repository is a grab-bag of small, standalone scripts (plus a `Makefile` for convenience) that I use for common tasks.

General layout:

- `image/`: image-related utilities (format conversion, generating downscaled variants, etc.)
- `other/`: unrelated utilities (e.g. batch video downloading)

Most scripts can be run either via `make <target>` or directly with `python3 ...`. Individual sections below document inputs/outputs and any extra dependencies.

# PNG <-> BMP

Dump PNG files into `image/png2bmp/pngs` and/or BMP files into `image/png2bmp/bmps`, then run:

```bash
make png2bmp
```

This auto-converts both ways:

- PNGs in `image/png2bmp/pngs` -> BMPs in `image/png2bmp/bmps`
- BMPs in `image/png2bmp/bmps` -> PNGs in `image/png2bmp/pngs`

It never deletes the source files.

Or directly:

```bash
python3 image/png2bmp/png_to_bmp.py
```

Requires Python 3 and Pillow:

```bash
sudo apt install python3-pil
```

# Subimages (Downscale)

Put `.png` or `.bmp` images into `image/subimages/input` and run:

```bash
make subimages
```

To change how far it goes (generate up to $1/2^N$):

```bash
# up to 1/32 (2^5)
make subimages N=5
```

This generates resized copies at 1/2, 1/4, 1/8, ... up to 1/64 into `image/subimages/output`, preserving any subfolder structure.

Output files are written directly into `image/subimages/output` (no scale subfolders) and are named like `1_2_<original_name>`, `1_4_<original_name>`, etc. The output folder is wiped at the start of each run.

Or directly:

```bash
python3 image/subimages/create_subimages.py image/subimages/input -o image/subimages/output
```

Customize the scale set:

```bash
# generate 1/2..1/256
python3 image/subimages/create_subimages.py image/subimages/input -o image/subimages/output --max-denom 256

# generate only specific scales
python3 image/subimages/create_subimages.py image/subimages/input -o image/subimages/output --denoms 2,8,64
```

# Video Downloader

Downloads videos listed in a text file and writes them into `other/video_downloader/output/`.

Run:

```bash
make video_downloader
```

This target runs in “batch mode” (it won’t fail the whole `make` if a few links fail). See the report file for details.

By default, the downloader **does not** clear the output folder; it appends new downloads into `other/video_downloader/output/` and auto-suffixes names if needed.
If you want each run to start fresh, run the script directly with `--clear`.

## Input format

Edit `other/video_downloader/input.txt`.

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

A report is written to `other/video_downloader/output.txt` with per-link success/failure details (it updates as the run progresses).

This merge step typically requires `ffmpeg`:

```bash
sudo apt install ffmpeg
```

### Windows (single self-contained .exe)

If you want to run this on a Windows host with **no Python/yt-dlp/ffmpeg installs**, you can build a single-file executable using PyInstaller.

- Build on Windows: run [other/video_downloader/packaging/windows/build_onefile.cmd](other/video_downloader/packaging/windows/build_onefile.cmd)
- Output: `other/video_downloader/dist/video_downloader.exe`
- Usage: put an `input.txt` next to the `.exe` (same format as described above); it will create `output/` and `output.txt` next to the `.exe`.

Note: PyInstaller onefile executables unpack embedded binaries to a temporary folder at runtime, but everything is shipped inside the `.exe`.
