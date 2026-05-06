#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[4]
for repo_name in ("fran", "localiser", "utilz"):
    sys.path.insert(0, str(CODE_ROOT / repo_name))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import torch
from fran.inference.helpers import SmartImageLoader, load_oriented_images
from localiser.transforms.transforms import WindowOned
from monai.transforms.utility.dictionary import EnsureChannelFirstd
from utilz.helpers import info_from_filename


IMAGE_KEY = "image"
PT_EXT = ".pt"


def case_id_from_path(path: str | Path) -> str:
    return info_from_filename(Path(path).name, full_caseid=True)["case_id"]


def squeeze_to_volume(image: torch.Tensor) -> torch.Tensor:
    volume = torch.as_tensor(image).detach().cpu().float()
    while volume.ndim > 3:
        volume = volume[0]
    return volume


def load_pt_volume(path: str | Path, window: str = "a") -> torch.Tensor:
    data = SmartImageLoader(keys=[IMAGE_KEY])({IMAGE_KEY: Path(path)})
    data = EnsureChannelFirstd(keys=[IMAGE_KEY], channel_dim="no_channel")(data)
    data = WindowOned(keys=[IMAGE_KEY], window=window)(data)
    return squeeze_to_volume(data[IMAGE_KEY])


def load_image_volume(path: str | Path, window: str = "a") -> torch.Tensor:
    data = load_oriented_images(Path(path))[0]
    data = WindowOned(keys=[IMAGE_KEY], window=window)(data)
    return squeeze_to_volume(data[IMAGE_KEY])


def load_volume(path: str | Path, window: str = "a") -> torch.Tensor:
    path = Path(path)
    if path.suffix == PT_EXT:
        return load_pt_volume(path, window=window)
    return load_image_volume(path, window=window)


def normalise_image(image: torch.Tensor) -> np.ndarray:
    array = torch.as_tensor(image).detach().cpu().numpy().astype(np.float32)
    array -= array.min()
    scale = array.max()
    if scale > 0:
        array /= scale
    return array


def create_orthogonal_projections(volume: torch.Tensor) -> dict[str, np.ndarray]:
    return {
        "sag": normalise_image(volume.max(dim=0).values),
        "cor": normalise_image(volume.max(dim=1).values),
        "ax": normalise_image(volume.max(dim=2).values),
    }


def save_projection_figure(
    projections: dict[str, np.ndarray], case_id: str, output_path: str | Path
) -> Path:
    output_path = Path(output_path)
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), dpi=160)
    for axis, key in zip(axes, ("sag", "cor", "ax")):
        axis.imshow(projections[key].T, cmap="gray", origin="lower")
        axis.set_title(key)
        axis.axis("off")
    fig.suptitle(case_id, fontsize=16, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="jpg", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def save_volume_jpg(
    input_path: str | Path, output_folder: str | Path, window: str = "a"
) -> Path:
    input_path = Path(input_path)
    case_id = case_id_from_path(input_path)
    volume = load_volume(input_path, window=window)
    projections = create_orthogonal_projections(volume)
    return save_projection_figure(
        projections=projections,
        case_id=case_id,
        output_path=Path(output_folder) / f"{case_id}.jpg",
    )


def save_volume_jpgs(
    input_paths: list[str | Path], output_folder: str | Path, window: str = "a"
) -> list[Path]:
    return [save_volume_jpg(path, output_folder, window=window) for path in input_paths]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create one JPG with 3 orthogonal projections for each input volume."
    )
    parser.add_argument("input_paths", nargs="+", help="One or more .pt or medical-image paths.")
    parser.add_argument("--output-folder", required=True, type=Path)
    parser.add_argument("--window", default="a")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    outputs = save_volume_jpgs(args.input_paths, args.output_folder, window=args.window)
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
