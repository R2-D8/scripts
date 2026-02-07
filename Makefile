
.DEFAULT_GOAL := help

.PHONY: help venv deps clean_venv tools ffmpeg bootstrap png2bmp subimages video_downloader pdf_invert

VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
DEPS_STAMP := $(VENV)/.deps-installed

TOOLS_DIR := tools
FFMPEG_DIR := $(TOOLS_DIR)/ffmpeg
FFMPEG_BIN := $(FFMPEG_DIR)/bin/ffmpeg

# Prefer the repo venv if it exists, otherwise fall back to system python.
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
PYTHONFLAGS ?= -B

# If the repo venv exists, make its console scripts (e.g. yt-dlp) discoverable.
export PATH := $(abspath $(FFMPEG_DIR))/bin:$(abspath $(VENV))/bin:$(PATH)

# Standard per-target argument passthrough.
PNG2BMP_ARGS ?=
SUBIMAGES_ARGS ?=
VIDEO_DOWNLOADER_ARGS ?=
PDF_INVERT_ARGS ?=

venv:
	python3 -m venv $(VENV)
	$(VENV_PYTHON) -m pip install -U pip setuptools wheel

$(DEPS_STAMP): requirements.txt
	python3 -m venv $(VENV)
	$(VENV_PYTHON) -m pip install -U pip setuptools wheel
	$(VENV_PYTHON) -m pip install -r requirements.txt
	@touch $(DEPS_STAMP)

deps: $(DEPS_STAMP)

tools: ffmpeg

ffmpeg: $(FFMPEG_BIN)

$(FFMPEG_BIN):
	python3 $(TOOLS_DIR)/install_ffmpeg_static.py

# One-shot setup for fresh machines.
bootstrap: deps ffmpeg

help:
	@printf "Setup:\n"
	@printf "  %-17s %s\n" "bootstrap" "One-shot: create .venv, install deps, download ffmpeg"
	@printf "  %-17s %s\n" "deps"      "Install Python deps into .venv (requirements.txt)"
	@printf "  %-17s %s\n" "ffmpeg"    "Download local static ffmpeg into tools/ffmpeg"
	@printf "  %-17s %s\n" "tools"     "Install all local tools (currently: ffmpeg)"
	@printf "  %-17s %s\n" "clean_venv" "Remove .venv"
	@printf "\nScripts:\n"
	@printf "  %-17s %s\n" "png2bmp" "Convert between PNG/BMP (image/png2bmp/)"
	@printf "  %-17s %s\n" ""      "Args: PNG2BMP_ARGS='...'"
	@printf "  %-17s %s\n" ""      "Example: make png2bmp"
	@printf "  %-17s %s\n" "subimages" "Generate downscaled images (set N=<power>)"
	@printf "  %-17s %s\n" ""        "Args: SUBIMAGES_ARGS='...' (optional)"
	@printf "  %-17s %s\n" ""        "Example: make subimages N=5 SUBIMAGES_ARGS='--recursive'"
	@printf "  %-17s %s\n" "video_downloader" "Download URLs from video/video_downloader/input.txt"
	@printf "  %-17s %s\n" ""              "Args: VIDEO_DOWNLOADER_ARGS='...' (optional)"
	@printf "  %-17s %s\n" ""              "Example: make video_downloader VIDEO_DOWNLOADER_ARGS='--clear'"
	@printf "  %-17s %s\n" "pdf_invert" "Invert PDFs in pdf/invert_colors/input"
	@printf "  %-17s %s\n" ""         "Args: PDF_INVERT_ARGS='...' (optional)"
	@printf "  %-17s %s\n" ""         "Example: make pdf_invert PDF_INVERT_ARGS='--overwrite'"

clean_venv:
	rm -rf $(VENV)

# Subimages: generate 1/2, 1/4, ... up to 1/2^N
# Default N=6 -> up to 1/64
N ?= 6



png2bmp: $(DEPS_STAMP)
	$(PYTHON) $(PYTHONFLAGS) image/png2bmp/png_to_bmp.py $(PNG2BMP_ARGS)

subimages: $(DEPS_STAMP)
	max_denom=$$((1<<$(N))); \
	args="$(SUBIMAGES_ARGS)"; \
	case "$$args" in \
		*--denoms*|*--max-denom*|*--min-denom*) default_flag="" ;; \
		*) default_flag="--max-denom $$max_denom" ;; \
	esac; \
	$(PYTHON) $(PYTHONFLAGS) image/subimages/create_subimages.py image/subimages/input -o image/subimages/output $$default_flag $$args

video_downloader: $(DEPS_STAMP) ffmpeg
	$(PYTHON) $(PYTHONFLAGS) video/video_downloader/video_downloader.py --exit-zero -o video/video_downloader/output $(VIDEO_DOWNLOADER_ARGS)

pdf_invert: $(DEPS_STAMP)
	$(PYTHON) $(PYTHONFLAGS) pdf/invert_colors/invert_pdf_colors.py $(PDF_INVERT_ARGS)
