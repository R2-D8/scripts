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

This generates resized copies at 1/2, 1/4, 1/8, ... up to 1/64 into `subimages/output`, preserving any subfolder structure.
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

Before starting, the output folder is cleared (so each run starts fresh). If you don’t want that behavior, run the script directly with `--no-clear`.

## Input format

Edit `other/video_downloader/input.txt`.

- Any line that is a link (starts with `http://` or `https://`) is treated as a URL to download.
- The filename used for that URL is the previous non-empty, non-comment line.
- Blank lines are ignored.
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
