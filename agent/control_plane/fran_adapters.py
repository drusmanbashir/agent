from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fran.data.dataregistry import DS
from fran.data.datasource import Datasource
from fran.managers.project import Project
from fran.run.project import project_init

from agent.control_plane.models import FAILED, NOT_READY, READY, REPAIRABLE, StatusResult


def dataset_spec(name: str):
    return DS[name]


def dataset_specs(names: list[str]) -> list:
    return [dataset_spec(name) for name in names]


def inspect_datasource_local(name: str, num_processes: int = 1) -> StatusResult:
    try:
        spec = dataset_spec(name)
    except Exception as exc:
        return StatusResult(
            target="datasource",
            name=name,
            mode="local",
            status=FAILED,
            message=f"Unknown datasource key: {name}",
            details={"dataset_key": name, "error_type": type(exc).__name__, "error": str(exc)},
        )
    folder = Path(spec.folder).expanduser().resolve()
    h5_fname = folder / "fg_voxels.h5"
    details = {
        "dataset_key": name,
        "dataset_name": spec.ds,
        "folder": str(folder),
        "h5_fname": str(h5_fname),
        "images_dir": str(folder / "images"),
        "lms_dir": str(folder / "lms"),
    }
    if not folder.exists():
        return StatusResult(
            target="datasource",
            name=name,
            mode="local",
            status=FAILED,
            message=f"Datasource folder does not exist: {folder}",
            details=details,
        )
    if not (folder / "images").exists() or not (folder / "lms").exists():
        return StatusResult(
            target="datasource",
            name=name,
            mode="local",
            status=FAILED,
            message="Datasource folder is missing images/ or lms/.",
            details=details,
        )
    try:
        ds = Datasource(folder=folder, name=spec.ds, alias=spec.alias)
        summary = ds.update_datasource(
            return_voxels=False,
            num_processes=num_processes,
            multiprocess=num_processes > 1,
            dry_run=True,
        )
    except Exception as exc:
        details["error_type"] = type(exc).__name__
        details["error"] = str(exc)
        return StatusResult(
            target="datasource",
            name=name,
            mode="local",
            status=FAILED,
            message=f"Datasource inspection failed: {exc}",
            details=details,
        )
    details["summary"] = summary
    details["case_counts"] = {
        "added": len(summary["added_case_ids"]),
        "removed": len(summary["removed_case_ids"]),
        "kept": len(summary["kept_case_ids"]),
    }
    if h5_fname.exists() and not summary["added_case_ids"] and not summary["removed_case_ids"]:
        return StatusResult(
            target="datasource",
            name=name,
            mode="local",
            status=READY,
            message="Datasource fg_voxels.h5 is present and reconciled with current files.",
            details=details,
        )
    return StatusResult(
        target="datasource",
        name=name,
        mode="local",
        status=REPAIRABLE,
        message="Datasource fg_voxels.h5 is missing or out of sync with current files.",
        details=details,
    )


def ensure_datasource_local(name: str, num_processes: int = 1) -> StatusResult:
    inspection = inspect_datasource_local(name=name, num_processes=num_processes)
    if inspection.status == FAILED:
        return inspection
    spec = dataset_spec(name)
    folder = Path(spec.folder).expanduser().resolve()
    ds = Datasource(folder=folder, name=spec.ds, alias=spec.alias)
    repair_summary = ds.update_datasource(
        return_voxels=False,
        num_processes=num_processes,
        multiprocess=num_processes > 1,
        dry_run=False,
    )
    result = inspect_datasource_local(name=name, num_processes=num_processes)
    result.details["repair_summary"] = repair_summary
    return result


def inspect_project_local(
    title: str,
    mnemonic: str,
    datasources: list[str],
    num_processes: int = 1,
    test: bool = False,
) -> StatusResult:
    dependency_results = [inspect_datasource_local(name, num_processes) for name in datasources]
    details = {
        "project_title": title,
        "mnemonic": mnemonic,
        "requested_datasources": datasources,
        "test": test,
        "datasource_dependencies": [result.to_dict() for result in dependency_results],
    }
    failed_dependencies = [result.name for result in dependency_results if result.status == FAILED]
    unready_dependencies = [
        result.name for result in dependency_results if result.status in (NOT_READY, REPAIRABLE)
    ]
    project = Project(project_title=title)
    details["project_folder"] = str(project.project_folder)
    details["db"] = str(project.db)
    details["global_properties"] = str(project.global_properties_filename)
    if failed_dependencies:
        details["blocking_datasources"] = failed_dependencies
        return StatusResult(
            target="project",
            name=title,
            mode="local",
            status=FAILED,
            message="Project readiness is blocked by invalid datasource inputs.",
            details=details,
        )
    if unready_dependencies:
        details["blocking_datasources"] = unready_dependencies
        return StatusResult(
            target="project",
            name=title,
            mode="local",
            status=NOT_READY,
            message="Project readiness is blocked until datasource fg_voxels.h5 prerequisites are ready.",
            details=details,
        )
    registered_datasources = set()
    if project.db.exists():
        registered_datasources = {row[0] for row in project.sql_query("SELECT DISTINCT ds FROM datasources")}
    expected_datasources = {
        result.details["dataset_name"]
        for result in dependency_results
        if result.status in (READY, REPAIRABLE)
    }
    missing_registrations = sorted(expected_datasources.difference(registered_datasources))
    details["registered_datasources"] = sorted(registered_datasources)
    details["expected_registered_datasources"] = sorted(expected_datasources)
    details["missing_registered_datasources"] = missing_registrations
    if project.db.exists() and project.global_properties_filename.exists() and not missing_registrations:
        return StatusResult(
            target="project",
            name=title,
            mode="local",
            status=READY,
            message="Project database, global properties, and datasource registrations are present.",
            details=details,
        )
    return StatusResult(
        target="project",
        name=title,
        mode="local",
        status=REPAIRABLE,
        message="Project can be created or completed locally once datasource prerequisites are ready.",
        details=details,
    )


def ensure_project_local(
    title: str,
    mnemonic: str,
    datasources: list[str],
    num_processes: int = 1,
    test: bool = False,
) -> StatusResult:
    dependency_repairs = []
    for name in datasources:
        dependency_result = inspect_datasource_local(name=name, num_processes=num_processes)
        if dependency_result.status == REPAIRABLE:
            dependency_result = ensure_datasource_local(name=name, num_processes=num_processes)
        dependency_repairs.append(dependency_result.to_dict())
        if dependency_result.status != READY:
            return StatusResult(
                target="project",
                name=title,
                mode="local",
                status=FAILED,
                message="Project ensure stopped because at least one datasource dependency is still not ready.",
                details={
                    "project_title": title,
                    "mnemonic": mnemonic,
                    "requested_datasources": datasources,
                    "dependency_repairs": dependency_repairs,
                },
            )
    args = SimpleNamespace(
        title=title,
        mnemonic=mnemonic,
        datasources=datasources,
        test=test,
        num_processes=num_processes,
    )
    project_init.main(args)
    result = inspect_project_local(
        title=title,
        mnemonic=mnemonic,
        datasources=datasources,
        num_processes=num_processes,
        test=test,
    )
    result.details["dependency_repairs"] = dependency_repairs
    return result
