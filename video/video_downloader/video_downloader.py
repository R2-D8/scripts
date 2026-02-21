#!/usr/bin/env python3

import argparse
import datetime as _dt
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entry:
	name: str
	url: str


_INVALID_FILENAME_CHARS = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _is_frozen() -> bool:
	return bool(getattr(sys, "frozen", False))


def _bundle_root_dir() -> Path:
	"""Return the directory containing bundled resources when frozen.

	For PyInstaller onefile builds, this is typically sys._MEIPASS.
	"""
	meipass = getattr(sys, "_MEIPASS", None)
	if meipass:
		return Path(meipass)
	# Fallback: directory containing the executable.
	return Path(sys.executable).resolve().parent


def _prepend_to_path(dir_path: Path) -> None:
	current = os.environ.get("PATH", "")
	parts = [p for p in current.split(os.pathsep) if p]
	normalized = str(dir_path)
	if parts and parts[0] == normalized:
		return
	if normalized in parts:
		parts.remove(normalized)
	os.environ["PATH"] = os.pathsep.join([normalized, *parts])


def _maybe_prepend_repo_tools(script_dir: Path) -> None:
	"""Best-effort: make repo-local tools discoverable when running from source.

	This lets a freshly bootstrapped repo work even when the user runs this
	script directly (not via Makefile), without requiring manual activation.
	"""
	if _is_frozen():
		return
	# repo root is two levels up: video/video_downloader/
	repo_root = script_dir.parent.parent
	venv_bin = repo_root / ".venv" / "bin"
	tools_ffmpeg_bin = repo_root / "tools" / "ffmpeg" / "bin"
	if tools_ffmpeg_bin.exists():
		_prepend_to_path(tools_ffmpeg_bin)
	if venv_bin.exists():
		_prepend_to_path(venv_bin)


def _bundled_bin(name: str) -> str | None:
	bin_dir = _bundle_root_dir() / "bin"
	candidate = bin_dir / name
	if candidate.exists():
		_prepend_to_path(bin_dir)
		return str(candidate)
	return None


def _sanitize_filename_stem(name: str) -> str:
	stem = name.strip()
	stem = re.sub(r"\s+", " ", stem)
	stem = _INVALID_FILENAME_CHARS.sub("_", stem)
	# Replace any remaining odd characters with underscores for portable filenames.
	# Keep letters, digits, space, dot, underscore, hyphen.
	stem = re.sub(r"[^A-Za-z0-9 ._-]+", "_", stem)
	stem = stem.strip(" .")
	return stem or "video"


def _url_to_name_component(url: str) -> str:
	# Per requirement: strip scheme and substitute '/' with '_'.
	without_scheme = _URL_RE.sub("", url.strip())
	return without_scheme.replace("/", "_")


def _is_url(line: str) -> bool:
	return bool(_URL_RE.match(line))


def parse_entries(input_file: Path) -> list[Entry]:
	entries: list[Entry] = []
	last_title_candidate: str | None = None

	# Read all lines so we can look ahead (for optional metadata on the next line).
	# utf-8-sig tolerates a UTF-8 BOM (common on Windows Notepad files).
	lines = input_file.read_text(encoding="utf-8-sig").splitlines()
	idx = 0
	while idx < len(lines):
		line = lines[idx].strip()
		idx += 1

		if not line:
			# A blank line breaks the "name applies to next URL" association.
			last_title_candidate = None
			continue
		if line.startswith("#") or line.startswith("//"):
			continue

		if _is_url(line):
			url_component = _url_to_name_component(line)
			base_name = f"{last_title_candidate}_{url_component}" if last_title_candidate else url_component
			last_title_candidate = None

			# Optional: if the next meaningful line contains ':' (e.g. 01:27),
			# incorporate it into the filename as <name>___<timestamp-with-:_as_->_>.
			suffix: str | None = None
			lookahead = idx
			while lookahead < len(lines):
				next_line_raw = lines[lookahead]
				next_line = next_line_raw.strip()
				if not next_line:
					# Blank line means no metadata for this URL.
					break
				if next_line.startswith("#") or next_line.startswith("//"):
					lookahead += 1
					continue
				# If the next meaningful line is another URL, stop.
				if _is_url(next_line):
					break
				if ":" in next_line:
					suffix = next_line.replace(":", "_")
					# Consume this metadata line so it doesn't become a name candidate.
					idx = lookahead + 1
				break
				# Otherwise it's some other text; do not consume it.
				break

			name = f"{base_name}___{suffix}" if suffix else base_name
			entries.append(Entry(name=name, url=line))
			continue

		# Any non-url, non-comment line can act as the title for the next URL,
		# except lines containing ':' (commonly timestamps like 01:27).
		if ":" in line:
			last_title_candidate = None
			continue
		last_title_candidate = line

	return entries


def _choose_unique_stem(output_dir: Path, desired_stem: str) -> str:
	stem = desired_stem
	suffix = 2
	while True:
		matches = glob.glob(str(output_dir / f"{stem}.*"))
		if not matches:
			return stem
		stem = f"{desired_stem}_{suffix}"
		suffix += 1


def _require_yt_dlp() -> str:
	# If bundled (PyInstaller), prefer the embedded binary.
	bundled = _bundled_bin("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
	if bundled:
		return bundled

	exe = shutil.which("yt-dlp")
	if exe:
		return exe
	raise FileNotFoundError(
		"yt-dlp not found. Either install it or build a bundled executable.\n\n"
		"Linux install (recommended):\n"
		"  sudo apt install yt-dlp\n"
		"or:\n"
		"  python3 -m pip install -U yt-dlp\n\n"
		"Windows: see the packaging script under other/video_downloader/packaging/windows" 
	)


def _clear_output_dir(output_dir: Path) -> None:
	if not output_dir.exists():
		return
	if not output_dir.is_dir():
		raise NotADirectoryError(f"Output path exists but is not a directory: {output_dir}")
	for child in output_dir.iterdir():
		try:
			if child.is_dir() and not child.is_symlink():
				shutil.rmtree(child)
			else:
				child.unlink(missing_ok=True)
		except Exception as e:
			raise RuntimeError(f"Failed clearing output dir entry: {child}") from e


def download_entry(
	yt_dlp_exe: str,
	entry: Entry,
	output_dir: Path,
	format_selector: str,
	merge_output_format: str | None,
	fail_fast: bool,
	verbose: bool,
) -> tuple[bool, str | None, str | None, str]:
	desired_stem = _sanitize_filename_stem(entry.name)
	stem = _choose_unique_stem(output_dir, desired_stem)
	out_template = str(output_dir / f"{stem}.%(ext)s")
	printed_path_file = output_dir / f".{stem}.filepath.txt"
	printed_path_file.unlink(missing_ok=True)

	base_cmd: list[str] = [
		yt_dlp_exe,
		"--no-playlist",
		"--no-color",
		"--progress",
		"-f",
		format_selector,
		"-o",
		out_template,
		"--print-to-file",
		"after_move:filepath",
		str(printed_path_file),
		entry.url,
	]
	if verbose:
		base_cmd.insert(1, "--verbose")
	else:
		# Quiet mode removes extractor/info spam, but we keep the per-video progress bar via --progress.
		base_cmd.insert(1, "--no-warnings")
		base_cmd.insert(1, "--quiet")

	# Prefer MP4 output; if not possible, try AVI.
	# If the user explicitly set --merge-output-format, respect it (no fallback).
	merge_candidates = [merge_output_format] if merge_output_format else ["mp4", "avi"]

	# Return: (success, final_filepath, error_message, stem_used)
	last_error: subprocess.CalledProcessError | None = None
	last_error_text: str | None = None
	final_path: str | None = None
	for container in merge_candidates:
		printed_path_file.unlink(missing_ok=True)
		cmd = list(base_cmd)
		if container:
			cmd.insert(-1, "--merge-output-format")
			cmd.insert(-1, container)
		try:
			subprocess.run(cmd, check=True)
			if printed_path_file.exists():
				try:
					final_path = printed_path_file.read_text(encoding="utf-8", errors="replace").splitlines()[-1].strip()
				except Exception:
					final_path = None
			printed_path_file.unlink(missing_ok=True)
			if not final_path:
				# Fallback: pick any produced file matching stem.* (best-effort).
				matches = sorted(glob.glob(str(output_dir / f"{stem}.*")))
				final_path = matches[-1] if matches else None
			return True, final_path, None, stem
		except subprocess.CalledProcessError as e:
			last_error = e
			last_error_text = str(e)
			if merge_output_format:
				break
			if verbose:
				print(
					f"Attempt failed for '{entry.name}' with container '{container}', trying next...",
					file=sys.stderr,
				)
		finally:
			printed_path_file.unlink(missing_ok=True)

	if last_error is not None:
		print(f"Download failed for '{entry.name}'", file=sys.stderr)
		if fail_fast:
			raise last_error
	return False, None, last_error_text, stem


def main(argv: list[str]) -> int:
	# When frozen (PyInstaller), __file__ points inside the extracted bundle.
	# Users expect input/output next to the .exe.
	script_dir = (
		Path(sys.executable).resolve().parent
		if _is_frozen()
		else Path(__file__).resolve().parent
	)
	_maybe_prepend_repo_tools(script_dir)

	parser = argparse.ArgumentParser(
		description=(
			"Download videos listed in a text file. Any line that is a URL is treated as a download link. "
			"If the previous non-comment line is a name, it is used as the output filename. "
			"Otherwise, a filename is derived from the URL."
		)
	)
	parser.add_argument(
		"-i",
		"--input",
		"--input-dir",
		type=Path,
		default=script_dir / "input.txt",
		help="Path to input text file (default: input.txt next to the script)",
	)
	parser.add_argument(
		"-o",
		"--output",
		"--output-dir",
		type=Path,
		default=script_dir / "output",
		help="Output directory (default: output/ next to the script)",
	)
	parser.add_argument(
		"-f",
		"--format",
		default="bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
		help=(
			"yt-dlp format selector (default prefers mp4 when available). "
			"Example: 'bestvideo+bestaudio/best'"
		),
	)
	parser.add_argument(
		"--merge-output-format",
		default=None,
		help=(
			"If provided, forces that container via --merge-output-format (e.g. mp4). "
			"If omitted, the script will try mp4 then avi. "
			"This typically requires ffmpeg."
		),
	)
	parser.add_argument(
		"--fail-fast",
		action="store_true",
		help="Stop immediately on the first download error.",
	)
	parser.add_argument(
		"--verbose",
		action="store_true",
		help="Show full yt-dlp logs (less clean output).",
	)
	parser.add_argument(
		"--report",
		type=Path,
		default=None,
		help="Write a run report to this file (default: output.txt next to the script)",
	)
	parser.add_argument(
		"--exit-zero",
		action="store_true",
		help="Always exit 0 even if some downloads fail (useful for Makefile batches).",
	)
	parser.add_argument(
		"--clear",
		action="store_true",
		help="Clear the output directory before downloading (default: keep existing files).",
	)

	args = parser.parse_args(argv)

	if not args.input.exists():
		print(f"Input file not found: {args.input}", file=sys.stderr)
		return 2

	args.output_dir.mkdir(parents=True, exist_ok=True)
	# Default is to keep output/ contents (append mode).
	if args.clear:
		try:
			_clear_output_dir(args.output_dir)
		except Exception as e:
			print(f"Failed to clear output directory: {e}", file=sys.stderr)
			return 2

	try:
		entries = parse_entries(args.input)
	except Exception as e:
		print(f"Failed to parse input: {e}", file=sys.stderr)
		return 2

	if not entries:
		print("No entries found.")
		return 0

	try:
		yt_dlp_exe = _require_yt_dlp()
	except FileNotFoundError as e:
		print(str(e), file=sys.stderr)
		return 2

	ok = 0
	total = len(entries)
	report_path = args.report or (script_dir / "output.txt")
	report_path.parent.mkdir(parents=True, exist_ok=True)
	started_at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")

	with report_path.open("w", encoding="utf-8") as report:
		report.write(f"started_at: {started_at}\n")
		report.write(f"input: {args.input}\n")
		report.write(f"output_dir: {args.output_dir}\n")
		report.write(f"total_links: {total}\n")
		report.write(f"format: {args.format}\n")
		report.write(
			"merge_output_format: "
			+ (args.merge_output_format if args.merge_output_format else "(auto: mp4 then avi)")
			+ "\n"
		)
		report.write("\n")

		for current_index, entry in enumerate(entries, start=1):
			# Overall progress counter plus the current item.
			if sys.stdout.isatty():
				prefix = f"\n\033[96m[{current_index}/{total}]\033[0m"
			else:
				prefix = f"\n[{current_index}/{total}]"
			print(f"{prefix} {entry.name} :: {entry.url}")
			started_one = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
			report.write(f"[{current_index}/{total}] name={entry.name}\n")
			report.write(f"url={entry.url}\n")
			report.write(f"status=STARTED\n")
			report.write(f"started_at={started_one}\n")
			report.flush()
			try:
				os.fsync(report.fileno())
			except Exception:
				pass

			t0 = time.time()
			success, final_path, error_text, stem_used = download_entry(
				yt_dlp_exe=yt_dlp_exe,
				entry=entry,
				output_dir=args.output_dir,
				format_selector=args.format,
				merge_output_format=args.merge_output_format,
				fail_fast=args.fail_fast,
				verbose=args.verbose,
			)
			dt_s = time.time() - t0
			if success:
				ok += 1
				report.write("status=OK\n")
				report.write(f"stem={stem_used}\n")
				report.write(f"duration_s={dt_s:.2f}\n")
				if final_path:
					report.write(f"file={final_path}\n")
			else:
				report.write("status=FAIL\n")
				report.write(f"stem={stem_used}\n")
				report.write(f"duration_s={dt_s:.2f}\n")
				if error_text:
					report.write(f"error={error_text}\n")
			report.write("\n")
			report.flush()
			try:
				os.fsync(report.fileno())
			except Exception:
				pass

		finished_at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
		report.write(f"finished_at: {finished_at}\n")
		report.write(f"summary: {ok}/{total} succeeded\n")

	print(f"Done: {ok}/{total} succeeded. Output: {args.output_dir}")
	print(f"Report: {report_path}")
	if args.exit_zero:
		return 0
	return 0 if ok == total else 1


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))
