"""Publish a single 64x32 RGB565 frame by atomically writing a file."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path


FRAME_BYTE_SIZE = 4096


def default_frame_path() -> Path:
	return Path(
		os.getenv(
			"QGRAPHIC_FRAME_PATH",
			os.getenv("QGRAPHIC_FRAME_FILE", "latest_frame.bin"),
		)
	)


def read_frame_file(file_path: str | Path) -> bytes:
	"""Read a raw 64x32 RGB565 frame from disk.

	The file must contain exactly 4096 bytes.
	"""

	path = Path(file_path)
	data = path.read_bytes()
	_validate_frame_size(data, path)
	return data


def send_frame_bytes(frame_bytes: bytes, out_path: str | Path | None = None) -> None:
	"""Write a single 4096-byte frame to disk via an atomic swap."""

	_validate_frame_size(frame_bytes)
	path = default_frame_path() if out_path is None else Path(out_path)
	_atomic_write_bytes(path, frame_bytes)


def send_frame_file(
	file_path: str | Path,
	out_path: str | Path | None = None,
) -> None:
	"""Read and write a single frame file via an atomic swap."""

	frame_bytes = read_frame_file(file_path)
	send_frame_bytes(frame_bytes, out_path=out_path)


def _validate_frame_size(frame_bytes: bytes, path: Path | None = None) -> None:
	if len(frame_bytes) != FRAME_BYTE_SIZE:
		suffix = f": {path}" if path is not None else ""
		raise ValueError(
			f"Expected {FRAME_BYTE_SIZE} bytes, got {len(frame_bytes)} bytes{suffix}"
		)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
	with tmp_path.open("wb") as handle:
		handle.write(data)
		handle.flush()
		try:
			os.fsync(handle.fileno())
		except OSError:
			pass
	os.replace(tmp_path, path)
	try:
		os.utime(path, None)
	except OSError:
		pass


def _parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Publish a 64x32 RGB565 frame (4096 bytes) to disk."
	)
	parser.add_argument("file", help="Path to the raw frame file")
	parser.add_argument(
		"out_path",
		nargs="?",
		default=str(default_frame_path()),
		help="Destination frame path (default: latest_frame.bin)",
	)
	return parser.parse_args()


def main() -> int:
	args = _parse_args()
	try:
		send_frame_file(args.file, args.out_path)
	except ValueError as exc:
		raise SystemExit(str(exc))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
