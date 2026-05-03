from __future__ import annotations

import argparse


def _flatten(values: list[list[str]] | None) -> list[str]:
    flattened: list[str] = []
    if not values:
        return flattened
    for group in values:
        flattened.extend(group)
    return flattened


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project_edit",
        description="Edit an existing FRAN project.",
    )
    parser.add_argument(
        "-t",
        "--title",
        "--project-title",
        "--project",
        dest="project_title",
        required=True,
        help="Existing project title to edit.",
    )
    parser.add_argument(
        "-n",
        "--num-processes",
        type=int,
        default=1,
        help="Parallel workers to pass through to FRAN when processing datasources.",
    )
    parser.add_argument(
        "--add-datasource",
        dest="add_datasource",
        nargs="+",
        action="append",
        default=[],
        help="Datasource key(s) from fran.data.dataregistry.DS. Repeatable.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Mark added datasources as test datasources.",
    )
    return parser


def main(args: argparse.Namespace | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args() if args is None else args

    requested = _dedupe_preserve_order(_flatten(parsed.add_datasource))
    if not requested:
        parser.error("At least one edit is required. Pass --add-datasource <name>.")

    if parsed.num_processes < 1:
        parser.error("--num-processes must be >= 1.")

    from fran.data.dataregistry import DS
    from fran.managers.project import Project

    available = set(DS.names())
    unknown = [name for name in requested if name not in available]
    if unknown:
        known = ", ".join(sorted(available))
        raise SystemExit(f"Unknown datasource(s): {', '.join(unknown)}. Known datasources: {known}")

    project = Project(project_title=parsed.project_title)
    if not project.db.exists():
        raise SystemExit(
            f"Project '{parsed.project_title}' does not exist at {project.project_folder}. "
            "Use project_init first."
        )
    if not project.global_properties_filename.exists():
        raise SystemExit(
            f"Project '{parsed.project_title}' is missing {project.global_properties_filename.name}. "
            "Repair it with project_init before using project_edit."
        )

    existing_entries = project.global_properties.get("datasources", []) or []
    existing_names = {entry["ds"] for entry in existing_entries if isinstance(entry, dict) and "ds" in entry}
    skipped = [name for name in requested if name in existing_names]
    to_add = [name for name in requested if name not in existing_names]

    if skipped:
        print(f"Skipping existing datasource(s): {', '.join(skipped)}")

    if not to_add:
        print("No new datasources to add.")
        return 0

    datasources = [DS[name] for name in to_add]
    multiprocess = parsed.num_processes > 1
    test_flags = [parsed.test] * len(datasources)

    print(f"Project: {project.project_title}")
    print(f"Add datasource(s): {', '.join(to_add)}")
    print(f"num_processes: {parsed.num_processes}")
    print(f"test: {parsed.test}")

    project.add_data(datasources=datasources, test=test_flags, multiprocess=multiprocess)
    project.maybe_store_projectwide_properties(overwrite=False, multiprocess=multiprocess)

    refreshed_entries = project.global_properties.get("datasources", []) or []
    refreshed_names = [entry["ds"] for entry in refreshed_entries if isinstance(entry, dict) and "ds" in entry]
    print(f"Project datasources now: {', '.join(refreshed_names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
