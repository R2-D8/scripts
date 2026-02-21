
.DEFAULT_GOAL := help

.PHONY: help venv deps clean_venv tools ffmpeg bootstrap png2bmp subimages video_downloader pdf_invert pdf_invert_keep_text ppt_to_pdf

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

# Standard argument passthrough (used by all script targets).
ARGS ?=

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
	@printf "  %-24s %s\n" "bootstrap" "One-shot: create .venv, install deps, download ffmpeg"
	@printf "  %-24s %s\n" "deps"      "Install Python deps into .venv (requirements.txt)"
	@printf "  %-24s %s\n" "ffmpeg"    "Download local static ffmpeg into tools/ffmpeg"
	@printf "  %-24s %s\n" "tools"     "Install all local tools (currently: ffmpeg)"
	@printf "  %-24s %s\n" "clean_venv" "Remove .venv"
	@printf "\nUsage:\n"
	@printf "  %-24s %s\n" "make <target>" "Run a script via the Makefile"
	@printf "  %-24s %s\n" "ARGS='...'" "(optional) pass flags to the underlying script"
	@printf "\nScripts:\n"
	@printf "  %-24s %s\n" "png2bmp" "Convert between PNG/BMP (image/png2bmp/)"
	@printf "  %-24s %s\n" "" "Args: ARGS='...' (optional)"
	@printf "  %-24s %s\n" "" "Flags: (none)"
	@printf "  %-24s %s\n" "" "Note: png2bmp ignores ARGS (always auto mode)."
	@printf "  %-24s %s\n" "" "Example: make png2bmp"
	@printf "  %-24s %s\n" "subimages" "Generate downscaled images (set N=<exponent>, default N=6 -> max denom 64)"
	@printf "  %-24s %s\n" "" "Args: ARGS='...' (optional)"
	@printf "  %-24s %s\n" "" "Flags: -i/--input/--input-dir  -o/--output/--output-dir"
	@printf "  %-24s %s\n" "" "       -r/--recursive  --max-denom  --min-denom  --denoms"
	@printf "  %-24s %s\n" "" "Example: make subimages"
	@printf "  %-24s %s\n" "" "         N=5 ARGS='--recursive'"
	@printf "  %-24s %s\n" "video_downloader" "Download URLs from video/video_downloader/input.txt"
	@printf "  %-24s %s\n" "" "Args: ARGS='...' (optional)"
	@printf "  %-24s %s\n" "" "Flags: -i/--input/--input-dir  -o/--output/--output-dir"
	@printf "  %-24s %s\n" "" "       -f/--format  --merge-output-format  --fail-fast  --verbose"
	@printf "  %-24s %s\n" "" "       --report  --exit-zero  --clear"
	@printf "  %-24s %s\n" "" "Example: make video_downloader"
	@printf "  %-24s %s\n" "" "         ARGS='--clear'"
	@printf "  %-24s %s\n" "pdf_invert" "Invert PDFs (flattened) in pdf/invert_colors/input"
	@printf "  %-24s %s\n" "" "Args: ARGS='...' (optional)"
	@printf "  %-24s %s\n" "" "Flags: -i/--input/--input-dir  -o/--output/--output-dir"
	@printf "  %-24s %s\n" "" "       -r/--recursive  --dpi  --password  --overwrite  --exit-zero"
	@printf "  %-24s %s\n" "" "Example: make pdf_invert"
	@printf "  %-24s %s\n" "" "         ARGS='--overwrite'"
	@printf "  %-24s %s\n" "pdf_invert_keep_text" "Invert PDFs but try to keep text selectable"
	@printf "  %-24s %s\n" "" "Input: pdf/invert_colors_keep_text/input"
	@printf "  %-24s %s\n" "" "Args: ARGS='...' (optional)"
	@printf "  %-24s %s\n" "" "Flags: -i/--input/--input-dir  -o/--output/--output-dir"
	@printf "  %-24s %s\n" "" "       -r/--recursive  --invert-images  --password  --overwrite  --exit-zero"
	@printf "  %-24s %s\n" "" "Example: make pdf_invert_keep_text"
	@printf "  %-24s %s\n" "" "         ARGS='--invert-images'"
	@printf "  %-24s %s\n" "ppt_to_pdf" "Convert PPT/PPTX to PDFs via LibreOffice (soffice)"
	@printf "  %-24s %s\n" "" "Input: pdf/ppt_to_pdf/input"
	@printf "  %-24s %s\n" "" "Args: ARGS='...' (optional)"
	@printf "  %-24s %s\n" "" "Flags: -i/--input/--input-dir  -o/--output/--output-dir"
	@printf "  %-24s %s\n" "" "       -r/--recursive  --overwrite  --soffice  --timeout  --exit-zero"
	@printf "  %-24s %s\n" "" "Example: make ppt_to_pdf"

clean_venv:
	rm -rf $(VENV)

# Subimages: generate 1/2, 1/4, ... up to 1/2^N
# Default N=6 -> up to 1/64
N ?= 6



png2bmp: $(DEPS_STAMP)
	$(PYTHON) $(PYTHONFLAGS) image/png2bmp/png_to_bmp.py $(ARGS)

subimages: $(DEPS_STAMP)
	max_denom=$$((1<<$(N))); \
	args="$(ARGS)"; \
	case "$$args" in \
		*--denoms*|*--max-denom*|*--min-denom*) default_flag="" ;; \
		*) default_flag="--max-denom $$max_denom" ;; \
	esac; \
	$(PYTHON) $(PYTHONFLAGS) image/subimages/create_subimages.py \
		$$default_flag $$args

video_downloader: $(DEPS_STAMP) ffmpeg
	$(PYTHON) $(PYTHONFLAGS) video/video_downloader/video_downloader.py --exit-zero $(ARGS)

pdf_invert: $(DEPS_STAMP)
	$(PYTHON) $(PYTHONFLAGS) pdf/invert_colors/invert_pdf_colors.py $(ARGS)

pdf_invert_keep_text: $(DEPS_STAMP)
	$(PYTHON) $(PYTHONFLAGS) pdf/invert_colors_keep_text/invert_pdf_colors_keep_text.py $(ARGS)

ppt_to_pdf: $(DEPS_STAMP)
	$(PYTHON) $(PYTHONFLAGS) pdf/ppt_to_pdf/ppt_to_pdf.py $(ARGS)
