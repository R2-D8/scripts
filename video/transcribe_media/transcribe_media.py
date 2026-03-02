#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import wave
import zipfile
from pathlib import Path


_SUPPORTED_EXTS = {".mp3", ".mp4", ".avi"}

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Models list: https://alphacephei.com/vosk/models
_LANG_TO_MODEL: dict[str, tuple[str, str]] = {
	# Big generic models (higher accuracy, larger download/memory)
	"it": ("vosk-model-it-0.22", "https://alphacephei.com/vosk/models/vosk-model-it-0.22.zip"),
	"en": ("vosk-model-en-us-0.22", "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip"),
}


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
	"""Best-effort: make repo-local tools discoverable when running from source."""
	# repo root is two levels up: video/transcribe_media/
	repo_root = script_dir.parent.parent
	venv_bin = repo_root / ".venv" / "bin"
	tools_ffmpeg_bin = repo_root / "tools" / "ffmpeg" / "bin"
	if tools_ffmpeg_bin.exists():
		_prepend_to_path(tools_ffmpeg_bin)
	if venv_bin.exists():
		_prepend_to_path(venv_bin)


def _find_ffmpeg(script_dir: Path) -> str:
	_maybe_prepend_repo_tools(script_dir)
	found = shutil.which("ffmpeg")
	if found:
		return found

	# Fallback: try repo-local ffmpeg even if PATH isn't set.
	repo_root = script_dir.parent.parent
	candidate = repo_root / "tools" / "ffmpeg" / "bin" / "ffmpeg"
	return str(candidate) if candidate.exists() else "ffmpeg"


def _ensure_vosk_model(*, model_root: Path, model_name: str, model_zip_url: str) -> Path:
	"""Ensure the Vosk model exists locally; download it if missing."""
	model_dir = model_root / model_name
	if model_dir.exists():
		return model_dir

	model_root.mkdir(parents=True, exist_ok=True)

	with tempfile.TemporaryDirectory(prefix="vosk_model_") as tmp:
		tmp_dir = Path(tmp)
		zip_path = tmp_dir / f"{model_name}.zip"
		print(f"Downloading model: {model_zip_url}")
		urllib.request.urlretrieve(model_zip_url, zip_path)

		print(f"Extracting model to: {model_root}")
		with zipfile.ZipFile(zip_path, "r") as zf:
			zf.extractall(model_root)

	if not model_dir.exists():
		raise RuntimeError(f"Model extraction failed; expected {model_dir}")

	return model_dir


def _parse_timestamp_to_seconds(value: str) -> float:
	"""Parse a timestamp into seconds.

	Accepted formats:
	- SS
	- SS.mmm
	- MM:SS
	- HH:MM:SS
	- HH:MM:SS.mmm
	"""
	s = value.strip()
	if not s:
		raise ValueError("empty timestamp")

	# Plain seconds (int/float)
	if ":" not in s:
		return float(s)

	parts = s.split(":")
	if len(parts) not in (2, 3):
		raise ValueError(f"invalid timestamp: {value}")

	try:
		parts_f = [float(p) for p in parts]
	except Exception as exc:
		raise ValueError(f"invalid timestamp: {value}") from exc

	if len(parts_f) == 2:
		mm, ss = parts_f
		return mm * 60.0 + ss

	hh, mm, ss = parts_f
	return hh * 3600.0 + mm * 60.0 + ss


def _is_comment_or_blank(line: str) -> bool:
	s = line.strip()
	return (not s) or s.startswith("#") or s.startswith("//")


def _is_url(line: str) -> bool:
	return bool(_URL_RE.match(line.strip()))


def _try_parse_segment_line(line: str) -> tuple[float | None, float | None] | None:
	"""Try parse a '<start> <end>' line.

	Returns None if the line doesn't look like a segment line.
	Accepts 1 or 2 tokens. Use '-' to mean "unset".
	"""
	s = line.strip()
	if not s or s.startswith("#") or s.startswith("//"):
		return None

	# Allow commas too.
	s = s.replace(",", " ")
	parts = [p for p in s.split() if p]
	if len(parts) == 0 or len(parts) > 2:
		return None

	def parse_part(p: str) -> float | None:
		if p in ("-", "_"):
			return None
		return _parse_timestamp_to_seconds(p)

	try:
		start_s = parse_part(parts[0])
		end_s = parse_part(parts[1]) if len(parts) == 2 else None
	except Exception:
		return None

	# Require at least one value.
	if start_s is None and end_s is None:
		return None
	# Validate range if both present.
	try:
		_ffmpeg_trim_args(start_s=start_s, end_s=end_s)
	except Exception:
		return None
	return start_s, end_s


def _parse_input_txt(input_txt: Path) -> tuple[
	dict[str, tuple[float | None, float | None]],
	list[tuple[str, tuple[float | None, float | None]]],
]:
	"""Parse an input.txt.

	Rules:
	- A line can be a URL (download + transcribe) or a file reference (stem/path without extension).
	- The line immediately after a URL or file reference *may* contain '<start> <end>'.
	- Not all lines are necessarily meaningful; unknown file references are ignored later.
	"""
	url_segments: dict[str, tuple[float | None, float | None]] = {}
	file_refs: list[tuple[str, tuple[float | None, float | None]]] = []

	lines = input_txt.read_text(encoding="utf-8-sig", errors="replace").splitlines()
	i = 0
	while i < len(lines):
		line_raw = lines[i]
		line = line_raw.strip()
		i += 1
		if _is_comment_or_blank(line):
			continue

		seg: tuple[float | None, float | None] | None = None
		if i < len(lines):
			seg = _try_parse_segment_line(lines[i])
			if seg is not None:
				i += 1
		else:
			seg = None

		if _is_url(line):
			url_segments[line] = seg if seg is not None else (None, None)
		else:
			file_refs.append((line, seg if seg is not None else (None, None)))

	return url_segments, file_refs


def _ffmpeg_trim_args(*, start_s: float | None, end_s: float | None) -> list[str]:
	"""Build ffmpeg args to trim accurately.

	We put -ss after -i (slower but more accurate seeking).
	"""
	args: list[str] = []
	if start_s is not None and start_s < 0:
		raise ValueError("--start must be >= 0")
	if end_s is not None and end_s < 0:
		raise ValueError("--end must be >= 0")

	if start_s is None and end_s is None:
		return args

	if start_s is not None and end_s is not None:
		if end_s <= start_s:
			raise ValueError("--end must be > --start")
		duration = end_s - start_s
		# -ss AFTER -i for accuracy
		args.extend(["-ss", f"{start_s:.3f}", "-t", f"{duration:.3f}"])
		return args

	if start_s is not None:
		args.extend(["-ss", f"{start_s:.3f}"])
		return args

	# Only end: treat as duration from 0
	args.extend(["-t", f"{end_s:.3f}"])
	return args


def _extract_audio_to_wav_segment(
	*,
	input_path: Path,
	wav_path: Path,
	ffmpeg: str,
	start_s: float | None,
	end_s: float | None,
) -> None:
	trim_args = _ffmpeg_trim_args(start_s=start_s, end_s=end_s)
	cmd = [
		ffmpeg,
		"-y",
		"-i",
		str(input_path),
		*trim_args,
		"-vn",
		"-ac",
		"1",
		"-ar",
		"16000",
		"-f",
		"wav",
		str(wav_path),
	]
	proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
	if proc.returncode != 0:
		raise RuntimeError(
			"ffmpeg failed\n"
			f"Command: {' '.join(cmd)}\n"
			f"stderr:\n{proc.stderr.strip()}"
		)


def _transcribe_with_vosk(
	input_path: Path,
	model,
	ffmpeg: str,
	*,
	start_s: float | None,
	end_s: float | None,
) -> str:
	with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp:
		wav_path = Path(tmp) / "audio.wav"
		_extract_audio_to_wav_segment(
			input_path=input_path,
			wav_path=wav_path,
			ffmpeg=ffmpeg,
			start_s=start_s,
			end_s=end_s,
		)

		wf = wave.open(str(wav_path), "rb")
		try:
			if wf.getnchannels() != 1:
				raise RuntimeError("Unexpected WAV channels (expected mono)")

			rec = model.KaldiRecognizer(wf.getframerate())

			chunks: list[str] = []
			while True:
				data = wf.readframes(4000)
				if len(data) == 0:
					break
				if rec.AcceptWaveform(data):
					res = json.loads(rec.Result())
					text = (res.get("text") or "").strip()
					if text:
						chunks.append(text)

			final = json.loads(rec.FinalResult())
			final_text = (final.get("text") or "").strip()
			if final_text:
				chunks.append(final_text)

			return " ".join(chunks).strip()
		finally:
			wf.close()


def _load_vosk_model(model_dir: Path):
	try:
		import vosk  # type: ignore
	except ImportError as exc:
		raise RuntimeError(
			"Missing dependency 'vosk'. Run: make deps (or pip install -r requirements.txt)"
		) from exc

	# Model is expensive to load; keep it for the entire run.
	model = vosk.Model(str(model_dir))

	# Provide a tiny wrapper so we can keep _transcribe_with_vosk simple.
	class _ModelWrapper:
		def __init__(self, inner):
			self._inner = inner

		def KaldiRecognizer(self, sample_rate: int):
			return vosk.KaldiRecognizer(self._inner, sample_rate)

	return _ModelWrapper(model)


def _download_from_input_txt(*, downloader_script: Path, input_txt: Path, downloads_dir: Path, report_path: Path) -> None:
	"""Run the existing video downloader script for an input.txt file (best-effort)."""
	downloads_dir.mkdir(parents=True, exist_ok=True)
	report_path.parent.mkdir(parents=True, exist_ok=True)

	cmd = [
		sys.executable,
		str(downloader_script),
		"--exit-zero",
		"--input-dir",
		str(input_txt),
		"--output-dir",
		str(downloads_dir),
		"--report",
		str(report_path),
	]
	proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
	if proc.returncode != 0:
		# Downloader in --exit-zero mode should generally return 0, but be tolerant.
		raise RuntimeError(f"Downloader failed (exit={proc.returncode}). Output:\n{proc.stdout.strip()}")


def _parse_downloader_report(report_path: Path) -> dict[str, Path]:
	"""Parse downloader report and return mapping: url -> downloaded file path."""
	if not report_path.exists():
		return {}

	url_to_file: dict[str, Path] = {}
	current_url: str | None = None
	current_status: str | None = None

	for raw in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
		line = raw.strip()
		if not line:
			current_url = None
			current_status = None
			continue
		if line.startswith("url="):
			current_url = line.removeprefix("url=").strip()
			continue
		if line.startswith("status="):
			current_status = line.removeprefix("status=").strip()
			continue
		if line.startswith("file=") and current_url and current_status == "OK":
			file_str = line.removeprefix("file=").strip()
			try:
				url_to_file[current_url] = Path(file_str)
			except Exception:
				pass

	return url_to_file


def _is_relative_to(path: Path, possible_parent: Path) -> bool:
	try:
		path.relative_to(possible_parent)
		return True
	except Exception:
		return False


def _iter_media_files(input_dir: Path, recursive: bool) -> list[Path]:
	if recursive:
		candidates = (p for p in input_dir.rglob("*") if p.is_file())
	else:
		candidates = (p for p in input_dir.glob("*") if p.is_file())

	files: list[Path] = []
	for path in candidates:
		if path.suffix.lower() in _SUPPORTED_EXTS:
			files.append(path)
	return sorted(files)


def main() -> int:
	script_dir = Path(__file__).resolve().parent
	default_input = script_dir / "input"
	default_output = script_dir / "output"
	default_model_root = script_dir / "model"

	parser = argparse.ArgumentParser(
		description=(
			"Transcribe media files from a directory (.mp3, .mp4, .avi) into per-file .txt transcripts. "
			"If --recursive is used, subdirectories are scanned and the output directory mirrors the same structure."
		)
	)
	parser.add_argument(
		"-i",
		"--input-dir",
		type=Path,
		default=default_input,
		help=f"Input directory (default: {default_input})",
	)
	parser.add_argument(
		"-o",
		"--output-dir",
		type=Path,
		default=default_output,
		help=f"Output directory (default: {default_output})",
	)
	parser.add_argument(
		"-l",
		"--language",
		choices=sorted(_LANG_TO_MODEL.keys()),
		default="it",
		help="Transcription language (default: it)",
	)
	parser.add_argument(
		"--start",
		type=str,
		default=None,
		help="Start timestamp for transcription segment (e.g. 12.5, 01:23, 00:01:23.500)",
	)
	parser.add_argument(
		"--end",
		type=str,
		default=None,
		help="End timestamp for transcription segment (same format as --start)",
	)
	parser.add_argument(
		"-r",
		"--recursive",
		action="store_true",
		help="Recurse into subdirectories (output mirrors input structure)",
	)

	args = parser.parse_args()
	input_dir: Path = args.input_dir
	output_dir: Path = args.output_dir
	language: str = args.language
	start_raw: str | None = args.start
	end_raw: str | None = args.end
	recursive: bool = args.recursive

	if not input_dir.exists() or not input_dir.is_dir():
		print(f"Input directory not found: {input_dir}", file=sys.stderr)
		return 2

	# Best-effort: make repo-local tools discoverable when running directly.
	_maybe_prepend_repo_tools(script_dir)

	start_s_default: float | None = None
	end_s_default: float | None = None
	try:
		if start_raw is not None:
			start_s_default = _parse_timestamp_to_seconds(start_raw)
		if end_raw is not None:
			end_s_default = _parse_timestamp_to_seconds(end_raw)
		# Validate pair here so we fail early.
		_ffmpeg_trim_args(start_s=start_s_default, end_s=end_s_default)
	except Exception as exc:
		print(f"Invalid --start/--end: {exc}", file=sys.stderr)
		return 2

	media_files = _iter_media_files(input_dir, recursive=recursive)

	# input.txt can exist in the input folder and (when --recursive) subfolders.
	if recursive:
		input_txts = sorted(
			[p for p in input_dir.rglob("input.txt") if p.is_file()],
			key=lambda p: (len(p.parts), str(p)),
		)
	else:
		p = input_dir / "input.txt"
		input_txts = [p] if p.exists() and p.is_file() else []

	# Parse input.txt for:
	# - URLs to download (and optional start/end per URL)
	# - file references (stem/path without extension) to override start/end per matching local file
	local_overrides: dict[Path, tuple[float | None, float | None]] = {}
	download_plan: list[tuple[Path, dict[str, tuple[float | None, float | None]]]] = []

	for input_txt in input_txts:
		base_dir = input_txt.parent
		try:
			url_segments, file_refs = _parse_input_txt(input_txt)
		except Exception as exc:
			print(f"Failed to parse {input_txt}: {exc}", file=sys.stderr)
			return 2

		if url_segments:
			download_plan.append((base_dir, url_segments))

		if not file_refs or not media_files:
			continue
		base_files = [f for f in media_files if _is_relative_to(f, base_dir)]
		if not base_files:
			continue

		# Indices for matching file references.
		by_stem: dict[str, list[Path]] = {}
		by_rel_no_ext: dict[str, list[Path]] = {}
		for f in base_files:
			try:
				rel = f.relative_to(base_dir).as_posix()
			except Exception:
				continue
			rel_no_ext = str(Path(rel).with_suffix("")).replace("\\", "/")
			by_rel_no_ext.setdefault(rel_no_ext, []).append(f)
			by_stem.setdefault(f.stem, []).append(f)

		for key, seg in file_refs:
			# Only apply if a segment is explicitly provided.
			if seg == (None, None):
				continue
			key_norm = key.strip().replace("\\", "/")
			matches: list[Path]
			if "/" in key_norm:
				matches = list(by_rel_no_ext.get(key_norm, []))
			else:
				matches = list(by_stem.get(key_norm, []))
			if not matches:
				# Not necessarily a file; ignore.
				continue
			for m in matches:
				local_overrides[m] = seg

	# Run downloads per input.txt base_dir.
	downloaded_files: list[Path] = []
	download_overrides: dict[Path, tuple[float | None, float | None]] = {}
	if download_plan:
		repo_root = script_dir.parent.parent
		downloader_script = repo_root / "video" / "video_downloader" / "video_downloader.py"

		for base_dir, url_segments in download_plan:
			try:
				rel_base = base_dir.relative_to(input_dir)
			except Exception:
				rel_base = Path(".")
			downloads_dir = (output_dir / "downloads" / rel_base) if recursive else (output_dir / "downloads")
			report_path = downloads_dir / "downloads_report.txt"

			with tempfile.TemporaryDirectory(prefix="transcribe_download_") as tmp:
				tmp_input = Path(tmp) / "urls_only.txt"
				tmp_input.write_text("\n".join(url_segments.keys()) + "\n", encoding="utf-8")
				try:
					_download_from_input_txt(
						downloader_script=downloader_script,
						input_txt=tmp_input,
						downloads_dir=downloads_dir,
						report_path=report_path,
					)
				except Exception as exc:
					print(f"Downloader step failed for {base_dir}: {exc}", file=sys.stderr)
					continue

			url_to_file = _parse_downloader_report(report_path)
			for url, file_path in url_to_file.items():
				seg = url_segments.get(url)
				if not seg or seg == (None, None):
					continue
				try:
					p2 = file_path.expanduser()
					p2 = p2.resolve() if p2.is_absolute() else (downloads_dir / p2).resolve()
				except Exception:
					p2 = file_path
				download_overrides[p2] = seg

			downloaded_files.extend(_iter_media_files(downloads_dir, recursive=False))

	if not media_files and not downloaded_files:
		print(f"No supported media files found under: {input_dir}")
		return 0

	ffmpeg = _find_ffmpeg(script_dir)

	model_name, model_zip_url = _LANG_TO_MODEL[language]
	try:
		model_dir = _ensure_vosk_model(model_root=default_model_root, model_name=model_name, model_zip_url=model_zip_url)
	except Exception as exc:
		print(f"Failed to prepare Vosk model: {exc}", file=sys.stderr)
		return 2

	try:
		vosk_model = _load_vosk_model(model_dir)
	except Exception as exc:
		print(f"Failed to load Vosk model: {exc}", file=sys.stderr)
		return 2

	n_fail = 0

	def _run_batch(
		*,
		files: list[Path],
		input_root: Path,
		out_root: Path,
		recursive_outputs: bool,
		segment_resolver,
		label_prefix: str = "",
	) -> None:
		nonlocal n_fail
		for in_path in files:
			try:
				rel = in_path.relative_to(input_root) if recursive_outputs else Path(in_path.name)
				out_path = (out_root / rel).with_suffix(".txt")
				out_path.parent.mkdir(parents=True, exist_ok=True)

				print(f"Transcribing: {label_prefix}{rel}")
				seg_start_s, seg_end_s = segment_resolver(in_path, rel)
				text = _transcribe_with_vosk(
					in_path,
					model=vosk_model,
					ffmpeg=ffmpeg,
					start_s=seg_start_s,
					end_s=seg_end_s,
				)
				out_path.write_text(text + "\n", encoding="utf-8")
			except Exception as exc:
				n_fail += 1
				print(f"ERROR: {in_path}: {exc}", file=sys.stderr)

	# 1) Local media files from input_dir
	if media_files:
		_run_batch(
			files=media_files,
			input_root=input_dir,
			out_root=output_dir,
			recursive_outputs=recursive,
			segment_resolver=lambda path, _rel: local_overrides.get(path, (start_s_default, end_s_default)),
		)

	# 2) Downloaded media files from output_dir/downloads
	if downloaded_files:
		# Transcribe each downloads_dir separately so output writes next to each file.
		for downloads_dir in sorted({p.parent for p in downloaded_files}):
			files_here = [p for p in downloaded_files if p.parent == downloads_dir]
			_run_batch(
				files=files_here,
				input_root=downloads_dir,
				out_root=downloads_dir,
				recursive_outputs=False,
				segment_resolver=lambda path, _rel: download_overrides.get(
					(path.expanduser().resolve() if path.exists() else path),
					(start_s_default, end_s_default),
				),
				label_prefix="downloads/",
			)

	if n_fail:
		print(f"Done with errors: {n_fail} file(s) failed", file=sys.stderr)
		return 1

	print("Done")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
