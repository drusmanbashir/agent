#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from dicom_utils.dcm_to_sitk import DCMCaseToSITK, mp_cleanup_folders
from xnat.helpers import collate_nii_foldertree


def run_case_workflow(
    dicom_folder: Path,
    output_folder: Path | None = None,
    dataset_name: str = "dicom",
    case_id: str | None = None,
    min_files_per_series: int = 1,
    max_series_per_case: int = 9999,
    overwrite: bool = False,
    tags: list[str] | None = None,
    convert_to_sitk: bool = False,
) -> dict:
    """
    Workflow for one case folder.
    Uses existing dicom_utils methods only:
    - DCMCaseToSITK.exclude_unsuitable() -> cleanup + filtering
    - DCMCaseToSITK.process()/process_all_series() -> conversion
    """
    out = output_folder or (dicom_folder / "sitk" / "images")
    workflow = DCMCaseToSITK(
        dataset_name=dataset_name,
        case_folder=dicom_folder,
        output_folder=out,
        case_id=case_id,
        tags=tags,
        max_series_per_case=max_series_per_case,
        min_files_per_series=min_files_per_series,
    )

    series_folders = workflow.exclude_unsuitable()
    result = {
        "case_folder": str(dicom_folder),
        "num_series": len(series_folders),
        "series_folders": [str(x) for x in series_folders],
    }

    if convert_to_sitk:
        workflow.process(overwrite=overwrite)
        result["output_names"] = [str(x) for x in getattr(workflow, "output_names", []) if x]

    return result


def run_dataset_cleanup_workflow(dataset_folder: Path) -> None:
    """
    Workflow for a folder containing case subfolders.
    Uses existing dicom_utils multiprocess cleanup.
    """
    mp_cleanup_folders(dataset_folder)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DICOM folder workflow using existing dicom_utils/xnat functions."
    )
    p.add_argument("dicom_folder", type=Path, help="Case folder (or dataset folder in --dataset-mode).")
    p.add_argument("--dataset-mode", action="store_true", help="Treat input as dataset root and only run cleanup on each case folder.")
    p.add_argument("--convert-to-sitk", action="store_true", help="Run DICOM->SITK conversion with DCMCaseToSITK.")
    p.add_argument("--output-folder", type=Path, default=None, help="SITK output folder.")
    p.add_argument("--dataset-name", default="dicom")
    p.add_argument("--case-id", default=None)
    p.add_argument("--min-files-per-series", type=int, default=1)
    p.add_argument("--max-series-per-case", type=int, default=9999)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--tags",
        nargs="*",
        default=None,
        help="DICOM tags used by existing sitk_name_from_series logic, e.g. StudyDate",
    )
    p.add_argument(
        "--collate-to",
        type=Path,
        default=None,
        help="Optional: collate generated NIfTI/NRRD files into one folder via xnat.helpers.collate_nii_foldertree.",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    dicom_folder = args.dicom_folder.resolve()

    if args.dataset_mode:
        run_dataset_cleanup_workflow(dicom_folder)
        print(f"Cleanup complete for dataset folder: {dicom_folder}")
        return

    result = run_case_workflow(
        dicom_folder=dicom_folder,
        output_folder=args.output_folder,
        dataset_name=args.dataset_name,
        case_id=args.case_id,
        min_files_per_series=args.min_files_per_series,
        max_series_per_case=args.max_series_per_case,
        overwrite=args.overwrite,
        tags=args.tags,
        convert_to_sitk=args.convert_to_sitk,
    )

    print(result)
    if args.collate_to and args.convert_to_sitk:
        src = args.output_folder or (dicom_folder / "sitk" / "images")
        collate_nii_foldertree(src, args.collate_to, fname_cond="")
        print(f"Collated outputs to: {args.collate_to}")


if __name__ == "__main__":
    main()
