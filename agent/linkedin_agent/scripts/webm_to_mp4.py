#!/usr/bin/env python3
"""Convert .webm video files to .mp4 (H.264/AAC) using ffmpeg."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a .webm file to an .mp4 file using ffmpeg."
    )
    parser.add_argument("input", type=Path, help="Input .webm file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .mp4 file (default: input path with .mp4 extension)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it already exists",
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=20,
        help="x264 CRF value (lower is higher quality, default: 20)",
    )
    parser.add_argument(
        "--preset",
        default="medium",
        help="x264 preset (default: medium)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if shutil.which("ffmpeg") is None:
        print("Error: ffmpeg not found in PATH.", file=sys.stderr)
        return 127

    in_path = args.input.expanduser().resolve()
    if not in_path.exists():
        print(f"Error: input file not found: {in_path}", file=sys.stderr)
        return 2
    if in_path.suffix.lower() != ".webm":
        print(f"Error: input must be a .webm file: {in_path}", file=sys.stderr)
        return 2

    out_path = (
        args.output.expanduser().resolve()
        if args.output
        else in_path.with_suffix(".mp4").resolve()
    )

    if out_path.exists() and not args.overwrite:
        print(
            f"Error: output already exists: {out_path} (use --overwrite)",
            file=sys.stderr,
        )
        return 3

    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if args.overwrite else "-n",
        "-i",
        str(in_path),
        "-c:v",
        "libx264",
        "-preset",
        args.preset,
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out_path),
    ]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg conversion failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode

    if not out_path.exists() or out_path.stat().st_size == 0:
        print("Conversion failed: output file was not created correctly.", file=sys.stderr)
        return 4

    print(f"Converted:\n  input:  {in_path}\n  output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
