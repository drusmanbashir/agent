#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from xnat.object_oriented import upload_nii


def _parse_tags(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(',') if x.strip()]


def _ask(prompt: str, default: str) -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    return val if val else default


def _ask_bool(prompt: str, default: bool) -> bool:
    d = "y" if default else "n"
    while True:
        val = input(f"{prompt} (y/n) [{d}]: ").strip().lower()
        if not val:
            return default
        if val in {"y", "yes", "true", "1"}:
            return True
        if val in {"n", "no", "false", "0"}:
            return False
        print("Please enter y or n.")


def _iter_files(folder: Path, pattern: str) -> Iterable[Path]:
    for p in sorted(folder.glob(pattern)):
        if p.is_file():
            yield p


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Upload a local folder to XNAT by calling upload_nii on each file."
    )
    ap.add_argument("--folder", type=Path, help="Folder containing files to upload")
    ap.add_argument("--pattern", default="*", help="Glob pattern inside folder (default: *)")
    ap.add_argument("--label", default=None, help="XNAT resource label, e.g. LABELMAP")
    ap.add_argument("--has-desc", action="store_true", help="Match by date+description (default: date only)")
    ap.add_argument("--no-has-date", action="store_true", help="Disable date matching")
    ap.add_argument("--xnat-tags", default=None, help="Comma-separated XNAT tags, e.g. manual,reviewed")
    ap.add_argument("--yes", action="store_true", help="Run non-interactively with provided/default args")
    args = ap.parse_args()

    folder = args.folder
    label = args.label
    has_desc = args.has_desc
    has_date = not args.no_has_date
    tags_raw = args.xnat_tags
    pattern = args.pattern

    if not args.yes:
        folder = Path(_ask("Folder", str(folder or "")))
        label = _ask("Label", label or "LABELMAP")
        has_desc = _ask_bool("has_desc", has_desc)
        has_date = _ask_bool("has_date", has_date)
        tags_raw = _ask("xnat_tags (comma-separated; empty for none)", tags_raw or "")
        pattern = _ask("Pattern", pattern)

    if folder is None:
        raise ValueError("--folder is required (or provide it interactively without --yes)")
    if label is None:
        label = "LABELMAP"

    folder = folder.expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        raise NotADirectoryError(f"Folder does not exist or is not a directory: {folder}")

    xnat_tags = _parse_tags(tags_raw or "")
    files = list(_iter_files(folder, pattern))
    if not files:
        print(f"No files matched in {folder} with pattern: {pattern}")
        return 1

    print("Upload plan:")
    print(f"  folder: {folder}")
    print(f"  pattern: {pattern}")
    print(f"  files: {len(files)}")
    print(f"  label: {label}")
    print(f"  has_desc: {has_desc}")
    print(f"  has_date: {has_date}")
    print(f"  xnat_tags: {xnat_tags}")

    uploaded = 0
    failed = 0
    for fpath in files:
        try:
            upload_nii(
                fpath,
                has_date=has_date,
                has_desc=has_desc,
                label=label,
                xnat_tags=xnat_tags,
            )
            uploaded += 1
        except Exception as e:
            failed += 1
            print(f"FAILED\t{fpath}\t{e}")

    print(f"Done. uploaded={uploaded} failed={failed} total={len(files)}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
