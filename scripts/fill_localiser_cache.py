#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = REPO_ROOT.parent
for repo_name in ("fran", "localiser", "utilz"):
    sys.path.insert(0, str(CODE_ROOT / repo_name))


IMAGE_SUFFIXES = (".nii.gz", ".nii", ".nrrd", ".mha", ".mhd")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fill missing YOLO localiser JSON cache for a folder of images."
    )
    parser.add_argument("images_folder", type=Path, help="Folder containing source images.")
    parser.add_argument("output_cache_folder", type=Path, help="Folder to write cache JSONs into.")
    parser.add_argument(
        "--localiser-regions",
        nargs="+",
        default=["abdomen"],
        help="One or more localiser regions. Default: abdomen.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Inference device: cpu, single gpu id like 0, or comma list like 0,1.",
    )
    parser.add_argument(
        "--prefix-rewrite",
        nargs=2,
        action="append",
        default=[],
        metavar=("SRC_PREFIX", "DST_PREFIX"),
        help="Rewrite staged filename prefixes so cache names can differ from source names.",
    )
    return parser


def strip_image_suffix(name: str) -> str:
    for suffix in IMAGE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def parse_device(device: str):
    if device == "cpu":
        return "cpu"
    parts = device.split(",")
    if len(parts) == 1:
        return int(parts[0])
    return [int(part) for part in parts]


def image_paths(images_folder: Path) -> list[Path]:
    return sorted(
        path
        for path in images_folder.iterdir()
        if path.is_file() and any(path.name.endswith(suffix) for suffix in IMAGE_SUFFIXES)
    )


def rewrite_stem(stem: str, prefix_rewrites: list[tuple[str, str]]) -> str:
    for src_prefix, dst_prefix in sorted(
        prefix_rewrites,
        key=lambda pair: len(pair[0]),
        reverse=True,
    ):
        if stem.startswith(src_prefix):
            return dst_prefix + stem[len(src_prefix) :]
    return stem


def staged_name(image_path: Path, prefix_rewrites: list[tuple[str, str]]) -> str:
    stem = strip_image_suffix(image_path.name)
    rewritten = rewrite_stem(stem, prefix_rewrites)
    return rewritten + "".join(image_path.suffixes)


class CacheFillInferer:
    def __init__(self, output_folder: Path, stage1_folder: Path, **kwargs):
        from fran.inference.cascade_yolo import LocaliserInfererPT

        class _Inferer(LocaliserInfererPT):
            def __init__(self, output_folder: Path, stage1_folder: Path, **inner_kwargs):
                self._output_folder = output_folder
                self._stage1_folder = stage1_folder
                super().__init__(**inner_kwargs)

            @property
            def output_folder(self):
                return self._output_folder

            @property
            def stage1_folder(self):
                return self._stage1_folder

        self.inferer = _Inferer(output_folder=output_folder, stage1_folder=stage1_folder, **kwargs)

    def run(self, images: list[Path]) -> None:
        self.inferer.run(images, overwrite=True)


def fill_localiser_cache(
    images_folder: Path,
    output_cache_folder: Path,
    localiser_regions: list[str],
    device: str,
    prefix_rewrites: list[tuple[str, str]],
) -> int:
    images_folder = images_folder.expanduser().resolve()
    output_cache_folder = output_cache_folder.expanduser().resolve()
    output_cache_folder.mkdir(parents=True, exist_ok=True)

    source_images = image_paths(images_folder)
    existing_cache_stems = {path.stem for path in output_cache_folder.glob("*.json")}
    missing_images = [
        image_path
        for image_path in source_images
        if strip_image_suffix(staged_name(image_path, prefix_rewrites)) not in existing_cache_stems
    ]

    print(f"images={len(source_images)} existing_json={len(existing_cache_stems)} missing={len(missing_images)}")
    if len(missing_images) == 0:
        return 0

    with TemporaryDirectory(prefix="fill_localiser_cache_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        staging_dir = tmpdir_path / "staged_images"
        staging_dir.mkdir()
        staged_images = []
        for image_path in missing_images:
            staged_image = staging_dir / staged_name(image_path, prefix_rewrites)
            staged_image.symlink_to(image_path)
            staged_images.append(staged_image)

        inferer = CacheFillInferer(
            output_folder=output_cache_folder,
            stage1_folder=tmpdir_path / "stage1",
            localiser_regions=localiser_regions,
            devices=parse_device(device),
            save_jpg=False,
        )
        inferer.run(staged_images)
    return len(missing_images)


def main() -> int:
    args = build_parser().parse_args()
    return fill_localiser_cache(
        images_folder=args.images_folder,
        output_cache_folder=args.output_cache_folder,
        localiser_regions=args.localiser_regions,
        device=args.device,
        prefix_rewrites=[tuple(pair) for pair in args.prefix_rewrite],
    )


if __name__ == "__main__":
    raise SystemExit(main())
