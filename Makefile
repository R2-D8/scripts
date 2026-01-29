.PHONY: png2bmp subimages

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
	$(PYTHON) $(PYTHONFLAGS) png2bmp/png_to_bmp.py

subimages:
	max_denom=$$((1<<$(N))); \
	$(PYTHON) $(PYTHONFLAGS) subimages/create_subimages.py subimages/input -o subimages/output --max-denom $$max_denom
