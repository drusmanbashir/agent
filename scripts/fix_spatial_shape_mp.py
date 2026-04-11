import multiprocessing as mp
import os
from pathlib import Path

import torch


def fixer(img_fn: Path):
    img = torch.load(img_fn, weights_only=False)
    meta = img.meta
    meta["spatial_shape"] = [int(x) for x in meta["spatial_shape"]]
    img.meta = meta
    torch.save(img, img_fn)


def _worker(img_fn: Path):
    try:
        fixer(img_fn)
        return str(img_fn), None
    except Exception as e:
        return str(img_fn), repr(e)


def run_multiprocess(func, items, num_processes=None):
    if num_processes is None:
        num_processes = max(1, (os.cpu_count() or 1) - 1)
    num_processes = max(1, min(num_processes, len(items)))
    if num_processes == 1:
        return [func(item) for item in items]

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=num_processes) as pool:
        return list(pool.imap_unordered(func, items))


if __name__ == "__main__":
    data_folder = Path(
        "/r/datasets/preprocessed/lidc/patches/spc_080_080_150_rspbb76320a_128128096"
    )
    img_fldr = data_folder / "images"
    imgs = sorted(img_fldr.glob("*.pt"))

    results = run_multiprocess(_worker, imgs, num_processes=24)
    failed = [(fn, err) for fn, err in results if err is not None]

    print(f"Processed: {len(results)} files")
    print(f"Failed: {len(failed)} files")
    if failed:
        print("Sample errors:")
        for fn, err in failed[:10]:
            print(f"- {fn}: {err}")
