#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Clone a deterministic subset of dataset images/lms pairs into a new folder."
        )
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Dataset root containing images/ and lms/, or the images/ folder itself.",
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="Destination dataset root to create or extend with images/ and lms/.",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        required=True,
        help="Maximum number of sorted filename pairs to copy.",
    )
    return parser


def resolve_dataset_root(source: Path) -> Path:
    source = source.expanduser().resolve()
    if (source / "images").is_dir() and (source / "lms").is_dir():
        return source
    if source.name == "images" and source.is_dir() and (source.parent / "lms").is_dir():
        return source.parent
    raise FileNotFoundError(
        f"Source must be a dataset root with images/ and lms/ or the images/ folder itself: {source}"
    )


def sorted_files(folder: Path) -> list[Path]:
    return sorted(path for path in folder.iterdir() if path.is_file())


def validate_pairs(images_dir: Path, lms_dir: Path) -> list[str]:
    image_names = [path.name for path in sorted_files(images_dir)]
    lm_names = [path.name for path in sorted_files(lms_dir)]

    if not image_names or not lm_names:
        raise RuntimeError("Source dataset has no files in images/ or lms/.")

    image_set = set(image_names)
    lm_set = set(lm_names)
    if image_set != lm_set:
        missing_lms = sorted(image_set - lm_set)
        missing_images = sorted(lm_set - image_set)
        details: list[str] = []
        if missing_lms:
            details.append(f"missing lms for {missing_lms[:3]}")
        if missing_images:
            details.append(f"missing images for {missing_images[:3]}")
        raise RuntimeError(
            "Filename mismatch between images/ and lms/: " + "; ".join(details)
        )

    return sorted(image_set)


def copy_subset(source_root: Path, destination_root: Path, limit: int) -> tuple[int, int]:
    if limit <= 0:
        raise RuntimeError("--limit must be greater than 0.")

    destination_root = destination_root.expanduser().resolve()
    if destination_root == source_root:
        raise RuntimeError("Destination must differ from source dataset root.")

    images_dir = source_root / "images"
    lms_dir = source_root / "lms"
    matched_names = validate_pairs(images_dir, lms_dir)
    selected_names = matched_names[:limit]

    if not selected_names:
        raise RuntimeError("No matched files available to copy.")

    dest_images = destination_root / "images"
    dest_lms = destination_root / "lms"
    dest_images.mkdir(parents=True, exist_ok=True)
    dest_lms.mkdir(parents=True, exist_ok=True)

    collisions = [
        name
        for name in selected_names
        if (dest_images / name).exists() or (dest_lms / name).exists()
    ]
    if collisions:
        raise RuntimeError(f"Destination already contains selected files, e.g. {collisions[:3]}")

    for name in selected_names:
        shutil.copy2(images_dir / name, dest_images / name)
        shutil.copy2(lms_dir / name, dest_lms / name)

    return len(selected_names), len(matched_names)


def main() -> int:
    args = build_parser().parse_args()

    try:
        source_root = resolve_dataset_root(args.source)
        copied, available = copy_subset(
            source_root=source_root,
            destination_root=args.destination,
            limit=args.limit,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"clone_dataset_subset: {exc}", file=sys.stderr)
        return 1

    print(
        f"Copied {copied} pairs from {source_root} to {args.destination.expanduser().resolve()} "
        f"({available} matched pairs available)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
