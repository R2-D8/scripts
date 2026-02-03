.PHONY: png2bmp subimages video_downloader

PYTHON ?= python3
PYTHONFLAGS ?= -B

# Subimages: generate 1/2, 1/4, ... up to 1/2^N
# Default N=6 -> up to 1/64
N ?= 6

# Backwards-compatible alias
ifdef SUBIMAGES_POW
N ?= $(SUBIMAGES_POW)
endif

png2bmp:
	$(PYTHON) $(PYTHONFLAGS) image/png2bmp/png_to_bmp.py

subimages:
	max_denom=$$((1<<$(N))); \
	$(PYTHON) $(PYTHONFLAGS) image/subimages/create_subimages.py image/subimages/input -o image/subimages/output --max-denom $$max_denom

video_downloader:
	$(PYTHON) $(PYTHONFLAGS) other/video_downloader/video_downloader.py --exit-zero -o other/video_downloader/output
