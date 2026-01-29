# PNG <-> BMP

Dump PNG files into `png2bmp/pngs` and/or BMP files into `png2bmp/bmps`, then run:

```bash
make png2bmp
```

This auto-converts both ways:

- PNGs in `png2bmp/pngs` -> BMPs in `png2bmp/bmps`
- BMPs in `png2bmp/bmps` -> PNGs in `png2bmp/pngs`

It never deletes the source files.

Or directly:

```bash
python3 png2bmp/png_to_bmp.py
```

Requires Python 3 and Pillow:

```bash
sudo apt install python3-pil
```

# Subimages (Downscale)

Put `.png` or `.bmp` images into `subimages/input` and run:

```bash
make subimages
```

To change how far it goes (generate up to $1/2^N$):

```bash
# up to 1/32 (2^5)
make subimages N=5
```

This generates resized copies at 1/2, 1/4, 1/8, ... up to 1/64 into `subimages/output`, preserving any subfolder structure.

Output files are written directly into `subimages/output` (no scale subfolders) and are named like `1_2_<original_name>`, `1_4_<original_name>`, etc. The output folder is wiped at the start of each run.

Or directly:

```bash
python3 subimages/create_subimages.py subimages/input -o subimages/output
```

Customize the scale set:

```bash
# generate 1/2..1/256
python3 subimages/create_subimages.py subimages/input -o subimages/output --max-denom 256

# generate only specific scales
python3 subimages/create_subimages.py subimages/input -o subimages/output --denoms 2,8,64
```
