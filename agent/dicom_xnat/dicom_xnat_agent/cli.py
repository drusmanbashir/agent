from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from workflow import (
        download_project_nifti_resources,
        prepare_for_xnat,
        project_dicom_to_nifti,
        upload_project_resources_by_filename,
    )
else:
    from .workflow import (
        download_project_nifti_resources,
        prepare_for_xnat,
        project_dicom_to_nifti,
        upload_project_resources_by_filename,
    )

from agent.storage_roots import storage_root


def _menu_prompt(title: str, options: list[str]) -> int:
    print(f"\n{title}")
    for i, opt in enumerate(options, start=1):
        print(f"  {i}) {opt}")
    print("  0) Back/Exit")
    while True:
        raw = input("Select option: ").strip()
        if raw.isdigit():
            n = int(raw)
            if 0 <= n <= len(options):
                return n
        print("Invalid choice, try again.")


def _input_with_default(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw or default


def _run_prepare(root_folder: Path, workers: int, debug: bool, multiprocess: bool) -> int:
    result = prepare_for_xnat(
        root_folder=root_folder,
        workers=workers,
        debug=debug,
        multiprocess=multiprocess,
    )
    print(f"root_folder: {result['root_folder']}")
    print(f"case_folders_processed: {result['case_folders_processed']}")
    print(f"workers: {result['workers']}")
    print(result["status"])
    return 0


def _yn(default: bool) -> str:
    return "y" if default else "n"


def _parse_subjects(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def _run_dcm2nifti(
    project_id: str,
    workers: int,
    include_date: bool,
    include_desc: bool,
    overwrite: bool,
    multiprocess: bool,
    subject_ids: list[str],
    ask: bool,
) -> int:
    if ask:
        workers_raw = _input_with_default("Workers", str(workers))
        workers = int(workers_raw) if workers_raw.isdigit() else workers
        multiprocess = _input_with_default("Multiprocess (y/n)", _yn(multiprocess)).lower().startswith("y")
        include_date = _input_with_default("Include date in filename (y/n)", _yn(include_date)).lower().startswith("y")
        include_desc = _input_with_default(
            "Include SeriesDescription in filename (y/n)", _yn(include_desc)
        ).lower().startswith("y")
        overwrite = _input_with_default("Overwrite existing resource label (y/n)", _yn(overwrite)).lower().startswith("y")
        subjects_default = ",".join(subject_ids)
        subjects_raw = _input_with_default("Subject filter (comma-separated, blank=all)", subjects_default)
        subject_ids = _parse_subjects(subjects_raw)

    result = project_dicom_to_nifti(
        project_id=project_id,
        workers=workers,
        include_date=include_date,
        include_desc=include_desc,
        overwrite=overwrite,
        multiprocess=multiprocess,
        subject_ids=subject_ids,
    )
    print(f"project_id: {result['project_id']}")
    print(f"mode: {result['mode']}")
    print(f"subject_filter_count: {result['subject_filter_count']}")
    print(f"workers: {result['workers']}")
    print(f"multiprocess: {result['multiprocess']}")
    print(result["status"])
    return 0


def _run_download_nifti(project_id: str, dest_folder: Path, ask: bool) -> int:
    if ask:
        project_id = _input_with_default("XNAT project ID", project_id)
        dest_folder = Path(_input_with_default("Destination folder", str(dest_folder))).expanduser()

    result = download_project_nifti_resources(
        project_id=project_id,
        dest_folder=dest_folder,
        label="IMAGE",
    )
    print(f"project_id: {result['project_id']}")
    print(f"label: {result['label']}")
    print(f"dest_folder: {result['dest_folder']}")
    print(f"project_dest_folder: {result['project_dest_folder']}")
    print(f"download_dest_folder: {result['download_dest_folder']}")
    print(f"collated_dest_folder: {result['collated_dest_folder']}")
    print(f"subjects_scanned: {result['subjects_scanned']}")
    print(f"subjects_with_matches: {result['subjects_with_matches']}")
    print(f"resources_matched: {result['resources_matched']}")
    print(f"fallback_resources: {result.get('fallback_resources', 0)}")
    print(f"fallback_files_downloaded: {result.get('fallback_files_downloaded', 0)}")
    print(f"failed_resources: {result.get('failed_resources', 0)}")
    print(result["status"])
    return 0


def _run_upload_resource(
    project_id: str,
    resource_folder: Path,
    resource_label: str,
    errors_file: Path | None,
    match_description: bool,
    create_missing_subject: bool,
    ask: bool,
) -> int:
    if ask:
        project_id = _input_with_default("XNAT project ID", project_id)
        resource_folder = Path(
            _input_with_default("Local resource folder", str(resource_folder))
        ).expanduser()
        resource_label = _input_with_default("Resource label", resource_label)
        match_description = _input_with_default(
            "Match description in scan selection (y/n)",
            _yn(match_description),
        ).lower().startswith("y")
        create_missing_subject = _input_with_default(
            "Create subject if missing (y/n)",
            _yn(create_missing_subject),
        ).lower().startswith("y")
        default_err = str(errors_file) if errors_file else str(resource_folder / "upload_resource_errors.tsv")
        errors_file = Path(_input_with_default("Errors file", default_err)).expanduser()

    result = upload_project_resources_by_filename(
        project_id=project_id,
        resource_folder=resource_folder,
        resource_label=resource_label,
        errors_file=errors_file,
        match_description=match_description,
        create_missing_subject=create_missing_subject,
    )
    print(f"project_id: {result['project_id']}")
    print(f"resource_folder: {result['resource_folder']}")
    print(f"resource_label: {result['resource_label']}")
    print(f"errors_file: {result['errors_file']}")
    print(f"files_scanned: {result['files_scanned']}")
    print(f"uploaded: {result['uploaded']}")
    print(f"skipped_existing_label: {result['skipped_existing_label']}")
    print(f"created_subjects: {result['created_subjects']}")
    print(f"errors: {result['errors']}")
    print(result["status"])
    return 0


def _run_menu() -> int:
    default_root = "/s/insync/datasets/bones"
    default_workers = "8"
    default_project = os.getenv("XNAT_PROJECT", "")
    default_dest = str(storage_root("tmp_root") / "xnat_downloads")
    default_resource_folder = str(storage_root("tmp_root") / "xnat_resources")
    default_resource_label = "LABELMAP"
    while True:
        choice = _menu_prompt(
            "DICOM XNAT Dashboard",
            [
                "Prepare Folder For XNAT (multiprocess)",
                "Prepare Folder For XNAT (single process)",
                "Project DICOM -> NIFTI (XNAT)",
                "Download NIFTI Resources (IMAGE)",
                "Upload Resources By Filename -> XNAT",
            ],
        )
        if choice == 0:
            return 0

        if choice == 1:
            root = Path(_input_with_default("Root folder", default_root)).expanduser()
            workers_in = _input_with_default("Workers", default_workers)
            workers = int(workers_in) if workers_in.isdigit() else 8
            debug = _input_with_default("Debug (y/n)", "n").lower().startswith("y")
            _run_prepare(root, workers, debug, multiprocess=True)
        elif choice == 2:
            root = Path(_input_with_default("Root folder", default_root)).expanduser()
            workers_in = _input_with_default("Workers", default_workers)
            workers = int(workers_in) if workers_in.isdigit() else 8
            debug = _input_with_default("Debug (y/n)", "n").lower().startswith("y")
            _run_prepare(root, workers, debug, multiprocess=False)
        elif choice == 3:
            project_id = _input_with_default("XNAT project ID", default_project)
            workers_in = _input_with_default("Workers", default_workers)
            workers = int(workers_in) if workers_in.isdigit() else 8
            _run_dcm2nifti(
                project_id=project_id,
                workers=workers,
                include_date=True,
                include_desc=True,
                overwrite=False,
                multiprocess=True,
                subject_ids=[],
                ask=True,
            )
        elif choice == 4:
            _run_download_nifti(
                project_id=default_project,
                dest_folder=Path(default_dest),
                ask=True,
            )
        elif choice == 5:
            _run_upload_resource(
                project_id=default_project,
                resource_folder=Path(default_resource_folder),
                resource_label=default_resource_label,
                errors_file=None,
                match_description=True,
                create_missing_subject=False,
                ask=True,
            )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dicom-xnat-agent",
        description="Prepare DICOM folder trees for XNAT upload.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    prep = sub.add_parser(
        "prepare",
        help=(
            "Delete unwanted files/folders and rewrite DICOM PatientID "
            "to direct subfolder name using multiprocessing."
        ),
    )
    prep.add_argument(
        "root_folder",
        type=Path,
        help="Root folder that contains case subfolders like 1, 2, 3, ...",
    )
    prep.add_argument("--workers", type=int, default=8, help="Number of worker processes.")
    prep.add_argument("--debug", action="store_true", help="Debug mode for utilz multiprocess helper.")
    prep.add_argument(
        "--no-multiprocess",
        action="store_true",
        help="Run in single process mode.",
    )
    sub.add_parser("menu", help="Interactive command line dashboard.")
    sub.add_parser("dashboard", help="Alias for menu.")

    d2n = sub.add_parser(
        "dcm2nifti",
        help=(
            "Convert DICOM scans to NIFTI resources in an XNAT project. "
            "Multiprocessing is enabled by default."
        ),
    )
    d2n.add_argument("project_id", help="XNAT project ID")
    d2n.add_argument("--workers", type=int, default=8, help="Number of worker processes (default: 8)")
    d2n.add_argument("--no-multiprocess", action="store_true", help="Run in single process mode.")
    d2n.add_argument("--no-date", action="store_true", help="Do not include date in NIFTI filename.")
    d2n.add_argument(
        "--no-desc",
        action="store_true",
        help="Do not include SeriesDescription in NIFTI filename.",
    )
    d2n.add_argument("--overwrite", action="store_true", help="Overwrite existing target resource label.")
    d2n.add_argument(
        "--subject",
        action="append",
        default=[],
        help="Process only this subject ID. Repeatable.",
    )
    d2n.add_argument(
        "--no-ask",
        action="store_true",
        help="Do not prompt interactively for naming/options.",
    )

    dln = sub.add_parser(
        "download-nifti",
        help="Download all IMAGE resources for a project to a destination folder.",
    )
    dln.add_argument("project_id", help="XNAT project ID")
    dln.add_argument("dest_folder", type=Path, help="Destination folder")
    dln.add_argument(
        "--no-ask",
        action="store_true",
        help="Do not prompt interactively for project/destination.",
    )

    upl = sub.add_parser(
        "upload-resource",
        help=(
            "Upload local resource files to matching project/subject/scan "
            "using filename metadata."
        ),
    )
    upl.add_argument("project_id", help="XNAT project ID")
    upl.add_argument("resource_folder", type=Path, help="Folder containing local resource files")
    upl.add_argument("resource_label", help="XNAT resource label to upload, e.g. LABELMAP")
    upl.add_argument(
        "--errors-file",
        type=Path,
        default=None,
        help="Path to write tab-separated errors log (default: under resource folder).",
    )
    upl.add_argument(
        "--no-ask",
        action="store_true",
        help="Do not prompt interactively for project/folder/label/errors file.",
    )
    upl.add_argument(
        "--ignore-description",
        action="store_true",
        help="Match only project+subject+date (do not use filename description).",
    )
    upl.add_argument(
        "--create-missing-subject",
        action="store_true",
        help="Create subject (and minimal session) when subject does not exist.",
    )
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd in {"menu", "dashboard"}:
        return _run_menu()

    if args.cmd == "prepare":
        return _run_prepare(
            root_folder=args.root_folder,
            workers=args.workers,
            debug=args.debug,
            multiprocess=not args.no_multiprocess,
        )
    if args.cmd == "dcm2nifti":
        return _run_dcm2nifti(
            project_id=args.project_id,
            workers=args.workers,
            include_date=not args.no_date,
            include_desc=not args.no_desc,
            overwrite=args.overwrite,
            multiprocess=not args.no_multiprocess,
            subject_ids=args.subject,
            ask=not args.no_ask,
        )
    if args.cmd == "download-nifti":
        return _run_download_nifti(
            project_id=args.project_id,
            dest_folder=args.dest_folder,
            ask=not args.no_ask,
        )
    if args.cmd == "upload-resource":
        return _run_upload_resource(
            project_id=args.project_id,
            resource_folder=args.resource_folder,
            resource_label=args.resource_label,
            errors_file=args.errors_file,
            match_description=not args.ignore_description,
            create_missing_subject=args.create_missing_subject,
            ask=not args.no_ask,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
