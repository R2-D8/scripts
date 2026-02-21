# Copilot coding instructions

## Big picture

- This repo is a grab-bag of small, **standalone Python scripts** organized by domain: `image/`, `pdf/`, `video/`, `other/`.
- There is no shared Python package; scripts are intended to run directly or via `make`.

## Canonical workflow (do this first)

- Setup everything (preferred): `make bootstrap`
    - Creates the repo-wide venv at `.venv/`
    - Installs all deps from `requirements.txt`
    - Downloads a local static `ffmpeg` into `tools/ffmpeg/`
- Alternative bootstrap (no Makefile): `python3 tools/bootstrap.py`
- Run scripts via `make <target>` where possible; the Makefile prepends `.venv/bin` and `tools/ffmpeg/bin` to `PATH` so tools like `yt-dlp` and `ffmpeg` are discoverable.

## Repo-specific conventions to follow

- Use `pathlib.Path` and make default paths **relative to the script directory** (examples: `pdf/invert_colors/invert_pdf_colors.py`, `video/video_downloader/video_downloader.py`).
- CLIs use `argparse` and usually follow an `input/` + `output/` (or `input.txt` + `output/`) layout next to the script.
- Makefile targets support argument passthrough via a single `ARGS` variable (example: `make video_downloader ARGS='--clear'`).
- Batch-friendly behavior exists and should be preserved:
    - `--exit-zero` is used by Makefile targets to avoid failing the whole run on partial errors (see video downloader).

## Adding a new script + Makefile target

- Put new utilities under the relevant domain folder (`image/`, `pdf/`, `video/`, `other/`) and keep them runnable as a standalone script.
- Prefer the repo’s common layout next to the script: `input/` + `output/` (or `input.txt` + `output/`) with defaults derived from `Path(__file__).resolve().parent`.
- Add a Makefile target that:
    - Depends on `$(DEPS_STAMP)` (and `ffmpeg` if needed)
    - Uses `$(PYTHON) $(PYTHONFLAGS)` so it runs with either `.venv` or system python
    - Supports arg passthrough via `ARGS ?=` and `make foo ARGS='...'`

Example Makefile pattern:

```makefile
ARGS ?=

foo: $(DEPS_STAMP)
    $(PYTHON) $(PYTHONFLAGS) path/to/foo.py $(ARGS)
```

- Also add a `help` line following the existing `@printf` style, and (if it’s user-facing) document the script briefly in `README.md` alongside the other targets.

## Output semantics (important)

- `image/subimages/create_subimages.py`: wipes the output directory at the start of each run (with safety checks).
- `video/video_downloader/video_downloader.py`: **does not clear** output by default; `--clear` wipes it.
- `pdf/invert_colors/invert_pdf_colors.py`: clears only existing `*.pdf` under output dir, then writes `<name>_invert.pdf`.

## External dependencies / integration points

- Python deps are repo-wide in `requirements.txt`: `Pillow`, `PyMuPDF` (imported as `fitz`), `yt-dlp`.
- `ffmpeg` should be treated as a repo-local tool under `tools/ffmpeg/bin` (installed by `make bootstrap` / `tools/install_ffmpeg_static.py`); don’t assume system ffmpeg is present.
- Windows packaging exists for the video downloader via `video/video_downloader/packaging/windows/*` (PyInstaller onefile). Frozen builds expect `input.txt`, `output/`, and `output.txt` next to the `.exe`.

## Editing rules that matter here

- Preserve each file’s indentation style (notably `video/video_downloader/video_downloader.py` uses tabs; avoid auto-reformatting).
- Keep scripts runnable both ways: `python3 path/to/script.py` and via `make <target>`.
- When adding a new script, also add a matching `make` target + `help` text, and prefer keeping it dependency-light (stdlib first; add to `requirements.txt` only when clearly needed).
