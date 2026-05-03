from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any
from zipfile import BadZipFile


def _maybe_add_local_repo_to_path(repo_name: str) -> None:
    import sys

    candidates = [
        Path(f"/home/ub/code/{repo_name}"),
        Path.cwd().parent / repo_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            p = str(candidate.resolve())
            if p not in sys.path:
                sys.path.insert(0, p)
            return


def _import_external_deps():
    try:
        from dicom_utils.helpers import delete_unwanted_files_folders
        from dicom_utils.metadata import dcm_id_fromfoldername
        from utilz.helpers import multiprocess_multiarg
        return delete_unwanted_files_folders, dcm_id_fromfoldername, multiprocess_multiarg
    except ModuleNotFoundError:
        _maybe_add_local_repo_to_path("dicom_utils")
        _maybe_add_local_repo_to_path("utilz")
        from dicom_utils.helpers import delete_unwanted_files_folders
        from dicom_utils.metadata import dcm_id_fromfoldername
        from utilz.helpers import multiprocess_multiarg
        return delete_unwanted_files_folders, dcm_id_fromfoldername, multiprocess_multiarg


def prepare_for_xnat(
    root_folder: Path,
    workers: int = 8,
    debug: bool = False,
    multiprocess: bool = True,
) -> dict[str, Any]:
    """
    Workflow:
    1) delete unwanted files/folders under root (existing function)
    2) set PatientID in each DICOM file to case-folder name for each direct child folder
       (existing function in multiprocessing)
    3) return summary
    """
    (
        delete_unwanted_files_folders,
        dcm_id_fromfoldername,
        multiprocess_multiarg,
    ) = _import_external_deps()

    root = Path(root_folder).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Root folder does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Root path is not a directory: {root}")

    # existing recursive cleaner from dicom_utils
    delete_unwanted_files_folders(root)

    case_folders = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
    args = [[case] for case in case_folders]
    # existing multiprocessing runner from utilz
    multiprocess_multiarg(
        dcm_id_fromfoldername,
        args,
        num_processes=workers,
        multiprocess=multiprocess,
        debug=debug,
    )

    return {
        "root_folder": str(root),
        "case_folders_processed": len(case_folders),
        "workers": workers,
        "debug": debug,
        "multiprocess": multiprocess,
        "status": "ready to upload on xnat",
    }


def _import_xnat_deps():
    try:
        from xnat.object_oriented import Proj, Subj, dcm2nii_parallel
        from xnat.helpers import readable_text
        return Proj, Subj, dcm2nii_parallel, readable_text
    except ModuleNotFoundError:
        _maybe_add_local_repo_to_path("xnat")
        from xnat.object_oriented import Proj, Subj, dcm2nii_parallel
        from xnat.helpers import readable_text
        return Proj, Subj, dcm2nii_parallel, readable_text


def _import_info_from_filename():
    try:
        from utilz.helpers import info_from_filename
        return info_from_filename
    except ModuleNotFoundError:
        _maybe_add_local_repo_to_path("utilz")
        from utilz.helpers import info_from_filename
        return info_from_filename


def _agent_repo_root() -> Path:
    # .../code/agent/agent/dicom_xnat/dicom_xnat_agent/workflow.py -> .../code/agent
    return Path(__file__).resolve().parents[3]


def _enforce_matching_ruleset() -> Path:
    """
    Enforce the declarative matching ruleset used for file<->subject matching.
    Keeps parser source fixed to utilz.helpers.info_from_filename.
    """
    ruleset_path = _agent_repo_root() / "automation" / "xnat" / "workflows" / "matching_rules.v1.yaml"
    if not ruleset_path.exists():
        raise FileNotFoundError(f"Required XNAT matching ruleset not found: {ruleset_path}")

    text = ruleset_path.read_text(encoding="utf-8")
    required_tokens = (
        "id: subject_id_matching_from_filename",
        "enabled: true",
        "module_path: ~/code/utilz/utilz/helpers.py",
        "function: info_from_filename",
    )
    missing = [tok for tok in required_tokens if tok not in text]
    if missing:
        raise ValueError(
            "XNAT matching ruleset failed validation; missing required entries: "
            + ", ".join(missing)
        )
    return ruleset_path


def project_dicom_to_nifti(
    project_id: str,
    workers: int = 8,
    include_date: bool = True,
    include_desc: bool = True,
    overwrite: bool = False,
    multiprocess: bool = True,
    subject_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Convert DICOM scans in an XNAT project to NIFTI resources.
    Uses your existing xnat repository objects and defaults to multiprocessing.
    """
    Proj, _, dcm2nii_parallel, _ = _import_xnat_deps()
    if not project_id.strip():
        raise ValueError("project_id cannot be empty")
    if workers < 1:
        raise ValueError("workers must be >= 1")

    subject_filter = [str(s).strip() for s in (subject_ids or []) if str(s).strip()]
    proj = Proj(project_id)

    # Strictly use xnat repo conversion code:
    # - dcm2nii_parallel for full-project multiprocessing
    # - Proj.dcm2nii for subject-filtered runs or single-process mode
    if multiprocess and len(subject_filter) == 0:
        dcm2nii_parallel(
            project_id,
            add_date=include_date,
            add_desc=include_desc,
            overwrite=overwrite,
            max_workers=workers,
        )
        mode = "dcm2nii_parallel"
    else:
        proj.dcm2nii(
            add_date=include_date,
            add_desc=include_desc,
            overwrite=overwrite,
            subs=subject_filter,
        )
        mode = "proj.dcm2nii"

    return {
        "project_id": project_id,
        "workers": workers,
        "multiprocess": multiprocess,
        "include_date": include_date,
        "include_desc": include_desc,
        "subject_filter_count": len(subject_filter),
        "subject_filter": subject_filter,
        "mode": mode,
        "status": "dcm2nifti complete",
    }


def download_project_nifti_resources(
    project_id: str,
    dest_folder: Path,
    label: str = "IMAGE",
) -> dict[str, Any]:
    """
    Download all matching resources for all subjects in a project.
    Default label is IMAGE for NIFTI image resources.
    """
    Proj, Subj, _, _ = _import_xnat_deps()
    try:
        from xnat.helpers import collate_nii_foldertree
    except ModuleNotFoundError:
        _maybe_add_local_repo_to_path("xnat")
        from xnat.helpers import collate_nii_foldertree
    if not project_id.strip():
        raise ValueError("project_id cannot be empty")
    if not str(dest_folder).strip():
        raise ValueError("dest_folder cannot be empty")

    dest = Path(dest_folder).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    project_dest = dest / project_id
    project_dest.mkdir(parents=True, exist_ok=True)

    proj = Proj(project_id)
    subs = list(proj.subs)

    def _resource_file_relpath(file_obj: Any) -> Path:
        try:
            attrs = file_obj.attributes()
            rel = attrs.get("path") or attrs.get("Name") or file_obj.id()
        except Exception:
            rel = file_obj.id()
        rel_txt = str(rel or file_obj.id()).strip().lstrip("/")
        return Path(rel_txt) if rel_txt else Path(str(file_obj.id()))

    def _download_resource_with_fallback(resource_obj: Any, out_dir: Path) -> tuple[bool, bool, int]:
        try:
            resource_obj.get(str(out_dir), extract=True)
            return True, False, 0
        except BadZipFile:
            try:
                files = list(resource_obj.files())
                if len(files) == 0:
                    print(
                        f"[warn] Resource {resource_obj.id()} ({resource_obj.label()}) "
                        "returned a non-zip payload and has no downloadable file entries."
                    )
                    return False, True, 0
                fallback_root = out_dir / str(resource_obj.id())
                fallback_root.mkdir(parents=True, exist_ok=True)
                downloaded = 0
                for file_obj in files:
                    relpath = _resource_file_relpath(file_obj)
                    target = fallback_root / relpath
                    target.parent.mkdir(parents=True, exist_ok=True)
                    file_obj.get(str(target))
                    downloaded += 1
                return True, True, downloaded
            except Exception as exc:
                print(
                    f"[warn] Fallback file-wise download failed for resource {resource_obj.id()} "
                    f"({resource_obj.label()}): {exc}"
                )
                return False, True, 0

    resources_matched = 0
    subjects_with_matches = 0
    fallback_resources = 0
    fallback_files_downloaded = 0
    failed_resources = 0
    for sub_res in subs:
        sub = Subj(sub_res)
        matches = [rsc for rsc in sub.rscs if rsc.label() == label]
        resources_matched += len(matches)
        if matches:
            subjects_with_matches += 1
            for match in matches:
                ok, used_fallback, files_downloaded = _download_resource_with_fallback(match.r, project_dest)
                if used_fallback:
                    fallback_resources += 1
                    fallback_files_downloaded += files_downloaded
                if not ok:
                    failed_resources += 1

    collate_nii_foldertree(project_dest, project_dest, fname_cond=".nii")

    return {
        "project_id": project_id,
        "label": label,
        "dest_folder": str(dest),
        "project_dest_folder": str(project_dest),
        "download_dest_folder": str(project_dest),
        "collated_dest_folder": str(project_dest),
        "subjects_scanned": len(subs),
        "subjects_with_matches": subjects_with_matches,
        "resources_matched": resources_matched,
        "fallback_resources": fallback_resources,
        "fallback_files_downloaded": fallback_files_downloaded,
        "failed_resources": failed_resources,
        "status": "resource download complete",
    }


def _normalize_desc(desc: str | None, readable_text) -> str:
    if not desc:
        return ""
    return readable_text(str(desc)).lower()


def _subject_scan_matches(
    sub,
    date: str | None,
    desc: str | None,
    readable_text,
    match_description: bool = True,
):
    scans = list(sub.scans)
    if not scans:
        return None, "subject_has_no_scans"

    want_date = (date or "").strip()
    want_desc = _normalize_desc(desc, readable_text) if match_description else ""

    if not want_date and not want_desc:
        if len(scans) == 1:
            return scans[0], ""
        return None, "scan_ambiguous_no_date_desc"

    def _match(scan) -> bool:
        if want_date and scan.date != want_date:
            return False
        if want_desc:
            scan_desc = _normalize_desc(scan.desc, readable_text)
            if scan_desc != want_desc:
                return False
        return True

    matched = [scan for scan in scans if _match(scan)]
    if len(matched) == 1:
        return matched[0], ""
    if len(matched) == 0:
        return None, "scan_not_found"
    return None, "scan_ambiguous_multiple_matches"


def upload_project_resources_by_filename(
    project_id: str,
    resource_folder: Path,
    resource_label: str,
    errors_file: Path | None = None,
    match_description: bool = True,
    create_missing_subject: bool = False,
) -> dict[str, Any]:
    """
    Upload local resource files to matching XNAT scans using filename metadata.
    Filename pattern parsed by utilz info_from_filename:
    <project>_<subject>[_<date>][_<desc>].*
    """
    _enforce_matching_ruleset()
    Proj, Subj, _, readable_text = _import_xnat_deps()
    info_from_filename = _import_info_from_filename()

    if not project_id.strip():
        raise ValueError("project_id cannot be empty")
    if not resource_label.strip():
        raise ValueError("resource_label cannot be empty")

    src = Path(resource_folder).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"resource_folder does not exist: {src}")
    if not src.is_dir():
        raise NotADirectoryError(f"resource_folder is not a directory: {src}")

    project = Proj(project_id)
    if not project.exists():
        raise ValueError(f"XNAT project does not exist: {project_id}")

    files = sorted([p for p in src.rglob("*") if p.is_file()])
    if not files:
        raise ValueError(f"No files found under resource_folder: {src}")

    if errors_file is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        err_path = src / f"upload_resource_errors_{ts}.tsv"
    else:
        err_path = Path(errors_file).expanduser().resolve()
    err_path.parent.mkdir(parents=True, exist_ok=True)

    stats = {
        "files_scanned": len(files),
        "uploaded": 0,
        "skipped_existing_label": 0,
        "created_subjects": 0,
        "errors": 0,
    }
    error_rows: list[dict[str, str]] = []

    for fpath in files:
        parsed = info_from_filename(fpath.name, full_caseid=False)
        proj_from_name = str(parsed.get("proj_title", "")).strip()
        subject_id = str(parsed.get("case_id", "")).strip()
        date = parsed.get("date")
        desc = parsed.get("desc")

        if not proj_from_name or not subject_id:
            stats["errors"] += 1
            error_rows.append(
                {
                    "file": str(fpath),
                    "reason": "filename_parse_failed",
                    "project_id_input": project_id,
                    "project_id_in_filename": proj_from_name,
                    "subject_id": subject_id,
                    "date": str(date or ""),
                    "desc": str(desc or ""),
                }
            )
            continue

        if proj_from_name != project_id:
            stats["errors"] += 1
            error_rows.append(
                {
                    "file": str(fpath),
                    "reason": "project_mismatch",
                    "project_id_input": project_id,
                    "project_id_in_filename": proj_from_name,
                    "subject_id": subject_id,
                    "date": str(date or ""),
                    "desc": str(desc or ""),
                }
            )
            continue

        sub = Subj.from_pt_id(subject_id, project_id)
        if not sub.exists():
            if create_missing_subject:
                subj_res = project.subject(subject_id)
                subj_res.create()
                stats["created_subjects"] += 1

                date_token = str(date or datetime.now().strftime("%Y%m%d"))
                exp_id = f"auto_{subject_id}_{date_token}"
                exp = subj_res.experiment(exp_id)
                if not exp.exists():
                    exp.create(experiments="xnat:ctSessionData")
                rsc = exp.resource(resource_label)
                if rsc.exists():
                    stats["skipped_existing_label"] += 1
                else:
                    rsc.file(fpath.name).put(str(fpath))
                    stats["uploaded"] += 1
                continue
            else:
                stats["errors"] += 1
                error_rows.append(
                    {
                        "file": str(fpath),
                        "reason": "subject_not_found",
                        "project_id_input": project_id,
                        "project_id_in_filename": proj_from_name,
                        "subject_id": subject_id,
                        "date": str(date or ""),
                        "desc": str(desc or ""),
                    }
                )
                continue

        scan, reason = _subject_scan_matches(
            sub,
            date,
            desc,
            readable_text,
            match_description=match_description,
        )
        if scan is None:
            stats["errors"] += 1
            error_rows.append(
                {
                    "file": str(fpath),
                    "reason": reason,
                    "project_id_input": project_id,
                    "project_id_in_filename": proj_from_name,
                    "subject_id": subject_id,
                    "date": str(date or ""),
                    "desc": str(desc or ""),
                }
            )
            continue

        if scan.has_rsc(resource_label):
            stats["skipped_existing_label"] += 1
            continue

        scan.add_rsc(fpath=fpath, label=resource_label)
        stats["uploaded"] += 1

    with err_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "file",
            "reason",
            "project_id_input",
            "project_id_in_filename",
            "subject_id",
            "date",
            "desc",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in error_rows:
            writer.writerow(row)

    return {
        "project_id": project_id,
        "resource_folder": str(src),
        "resource_label": resource_label,
        "errors_file": str(err_path),
        **stats,
        "status": "resource upload complete",
    }
