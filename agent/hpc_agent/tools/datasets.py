from __future__ import annotations

import argparse
import os
import posixpath
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from tools.cli import ConfigError, _load_hpc_config, _print_config_error, _run_command, _run_upload, _yes_no

CONFIG_ENV = "FRAN_CONF"
DATASETS_CONF = os.path.join(os.environ.get(CONFIG_ENV, ""), "datasets.yaml")
DATASETS_HPC_CONF = os.path.join(os.environ.get(CONFIG_ENV, ""), "datasets_hpc.yaml")
SYNC_SUBDIRS = ("images", "lms")
SYNC_PREFIXES = tuple(f"{subdir}/" for subdir in SYNC_SUBDIRS)


FileTimes = dict[str, int]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _strip_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _fallback_yaml_load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        if line[:1].isspace() or ":" not in line:
            raise ConfigError(f"Unsupported YAML structure in {path}; install PyYAML for nested YAML.")
        key, value = line.split(":", 1)
        data[key.strip()] = _strip_yaml_scalar(value)
    return data


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config not found: {path}")
    try:
        import yaml  # type: ignore
    except Exception:
        loaded = _fallback_yaml_load(path)
    else:
        loaded = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict):
        raise ConfigError(f"Config must be a mapping: {path}")
    return loaded


def _dataset_mapping(data: dict[str, Any]) -> dict[str, Any]:
    nested = data.get("datasets")
    if isinstance(nested, dict):
        return nested
    return data


def _split_remote_path(remote_path: str, dataset_name: str) -> tuple[str, str]:
    cleaned = remote_path.strip()
    if not cleaned:
        raise ConfigError(f"Dataset '{dataset_name}' remote path is empty in {DATASETS_HPC_CONF}")
    norm = cleaned.rstrip("/")
    remote_root = posixpath.dirname(norm)
    remote_subdir = posixpath.basename(norm)
    if not remote_root or remote_root == ".":
        raise ConfigError(f"Dataset '{dataset_name}' remote path must include parent dir in {DATASETS_HPC_CONF}")
    if not remote_subdir:
        raise ConfigError(f"Dataset '{dataset_name}' remote path must include subdir in {DATASETS_HPC_CONF}")
    return remote_root, remote_subdir


def _resolve_local_folder_entry(dataset_name: str, local_entry: Any) -> Path:
    if isinstance(local_entry, str):
        local_folder = Path(local_entry).expanduser()
    elif isinstance(local_entry, dict):
        local_raw = local_entry.get("local_folder") or local_entry.get("folder") or local_entry.get("path")
        if not isinstance(local_raw, str):
            raise ConfigError(
                f"Dataset '{dataset_name}' in {DATASETS_CONF} must provide local_folder/folder/path as string."
            )
        local_folder = Path(local_raw).expanduser()
    else:
        raise ConfigError(f"Dataset '{dataset_name}' in {DATASETS_CONF} has unsupported value type.")
    return local_folder


def _resolve_remote_target_entry(dataset_name: str, remote_entry: Any) -> tuple[str, str]:
    if isinstance(remote_entry, str):
        remote_root, remote_subdir = _split_remote_path(remote_entry, dataset_name)
    elif isinstance(remote_entry, dict):
        if isinstance(remote_entry.get("path"), str):
            remote_root, remote_subdir = _split_remote_path(str(remote_entry["path"]), dataset_name)
        elif isinstance(remote_entry.get("folder"), str) and str(remote_entry["folder"]).startswith("/"):
            remote_root, remote_subdir = _split_remote_path(str(remote_entry["folder"]), dataset_name)
        else:
            root_raw = remote_entry.get("remote_root") or remote_entry.get("root")
            subdir_raw = (
                remote_entry.get("remote_subdir")
                or remote_entry.get("subdir")
                or remote_entry.get("folder")
                or remote_entry.get("name")
            )
            if not isinstance(root_raw, str) or not root_raw.strip():
                raise ConfigError(
                    f"Dataset '{dataset_name}' in {DATASETS_HPC_CONF} must provide remote_root/root/path."
                )
            if not isinstance(subdir_raw, str) or not subdir_raw.strip():
                raise ConfigError(
                    f"Dataset '{dataset_name}' in {DATASETS_HPC_CONF} must provide remote_subdir/subdir/folder/name/path."
                )
            remote_root = root_raw.strip().rstrip("/")
            remote_subdir = subdir_raw.strip().strip("/")
    else:
        raise ConfigError(f"Dataset '{dataset_name}' in {DATASETS_HPC_CONF} has unsupported value type.")
    return remote_root, remote_subdir


def _resolve_dataset_upload(
    dataset_name: str,
    datasets_conf: dict[str, Any],
    datasets_hpc_conf: dict[str, Any],
) -> tuple[Path, str, str]:
    local_entry = datasets_conf.get(dataset_name)
    if local_entry is None:
        raise ConfigError(f"Dataset '{dataset_name}' missing in {DATASETS_CONF}")
    remote_entry = datasets_hpc_conf.get(dataset_name)
    if remote_entry is None:
        raise ConfigError(f"Dataset '{dataset_name}' missing in {DATASETS_HPC_CONF}")
    local_folder = _resolve_local_folder_entry(dataset_name, local_entry)
    remote_root, remote_subdir = _resolve_remote_target_entry(dataset_name, remote_entry)
    return local_folder, remote_root, remote_subdir


def run_dataset_upload(dataset_names: list[str], remote: str | None, yes: bool, config_path: Path | None) -> int:
    if not dataset_names:
        raise ConfigError("At least one dataset name is required.")
    config = _load_hpc_config(config_path)
    datasets_conf = _dataset_mapping(_load_yaml_mapping(Path(DATASETS_CONF).expanduser()))
    datasets_hpc_conf = _dataset_mapping(_load_yaml_mapping(Path(DATASETS_HPC_CONF).expanduser()))
    remote_login = remote or config["login"]

    for dataset_name in dataset_names:
        local_folder, remote_root, remote_subdir = _resolve_dataset_upload(dataset_name, datasets_conf, datasets_hpc_conf)
        print(
            f"Upload dataset '{dataset_name}': local_folder={local_folder} remote_root={remote_root} remote_subdir={remote_subdir}"
        )
        rc = _run_upload(
            remote=remote_login,
            local_folder=local_folder,
            remote_root=remote_root,
            remote_subdir=remote_subdir,
            yes=yes,
        )
        if rc != 0:
            return rc
    return 0


def _dataset_remote_path(remote_root: str, remote_subdir: str) -> str:
    return f"{remote_root.rstrip('/')}/{remote_subdir.strip('/')}"


def _is_safe_rel_sync_path(rel_path: str) -> bool:
    if not rel_path.startswith(SYNC_PREFIXES):
        return False
    pure = Path(rel_path)
    if pure.is_absolute():
        return False
    if any(part in {"", ".", ".."} for part in pure.parts):
        return False
    return True


def _validate_remote_abs_path(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if any(c in path for c in ("\n", "\r", "\x00")):
        return False
    norm = posixpath.normpath(path)
    return norm == path and norm != "/"


def _to_remote_abs_paths(remote_dataset_path: str, rel_paths: list[str]) -> list[str]:
    base = remote_dataset_path.rstrip("/")
    return [f"{base}/{rel_path}" for rel_path in rel_paths]


def _print_preflight_list(label: str, paths: list[str]) -> None:
    print(f"{label} ({len(paths)}):")
    for path in paths:
        print(f"  {path}")


def _remote_dir_exists(remote: str, remote_path: str, verbose: bool = True) -> bool:
    cmd = _remote_shell_cmd(remote, f"test -d {shlex.quote(remote_path)}")
    if verbose:
        print("Command:")
        print(f"  {shlex.join(cmd)}")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    stderr = proc.stderr.strip() if proc.stderr else ""
    raise ConfigError(f"Failed to probe remote dataset dir: {remote_path}. {stderr}".strip())


def _list_local_dataset_files(local_folder: Path) -> dict[str, FileTimes]:
    local_files: dict[str, FileTimes] = {}
    for subdir in SYNC_SUBDIRS:
        root = local_folder / subdir
        if not root.is_dir():
            continue
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(local_folder).as_posix()
            stat = file_path.stat()
            local_files[rel_path] = {
                "mtime": int(stat.st_mtime),
                "ctime": int(stat.st_ctime),
            }
    return local_files


def _remote_shell_cmd(remote: str, remote_cmd: str) -> list[str]:
    script = _repo_root() / "scripts" / "hpc_ssh.sh"
    if script.exists():
        return [str(script), "--login", remote, remote_cmd]
    return ["ssh", remote, remote_cmd]


def _list_remote_dataset_files(remote: str, remote_dataset_path: str, verbose: bool = True) -> dict[str, FileTimes]:
    remote_cmd = (
        f"base={shlex.quote(remote_dataset_path)}; "
        "for d in images lms; do "
        'p="$base/$d"; '
        'if [ -d "$p" ]; then find "$p" -type f -exec stat -c \'%n|%Y|%W\' {} +; fi; '
        "done"
    )
    cmd = _remote_shell_cmd(remote, remote_cmd)
    if verbose:
        print("Command:")
        print(f"  {shlex.join(cmd)}")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() if proc.stderr else ""
        raise ConfigError(f"Failed to list remote dataset files under {remote_dataset_path}. {stderr}".strip())

    remote_files: dict[str, FileTimes] = {}
    prefix = f"{remote_dataset_path.rstrip('/')}/"
    for line in proc.stdout.splitlines():
        raw = line.strip()
        if not raw or "|" not in raw:
            continue
        abs_path, mtime_raw, birth_raw = raw.rsplit("|", 2)
        abs_path = abs_path.strip()
        mtime_raw = mtime_raw.strip()
        birth_raw = birth_raw.strip()
        if not abs_path.startswith(prefix):
            continue
        rel_path = abs_path[len(prefix) :]
        if not rel_path.startswith(SYNC_PREFIXES):
            continue
        try:
            remote_files[rel_path] = {
                "mtime": int(mtime_raw),
                "ctime": int(birth_raw),
            }
        except ValueError:
            continue
    return remote_files


def _upload_selected_files(
    remote: str,
    local_folder: Path,
    remote_root: str,
    remote_subdir: str,
    selected_rel_paths: list[str],
    yes: bool,
) -> int:
    if not selected_rel_paths:
        print("No changed files in images/ or lms/ to upload.")
        return 0
    if not yes and not _yes_no("Run update upload now?", default=True):
        print("Cancelled.")
        return 0

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            for rel_path in selected_rel_paths:
                tmp.write(f"{rel_path}\n")
            tmp_path = tmp.name
        remote_dataset_path = _dataset_remote_path(remote_root, remote_subdir)
        rsync_wrapper = _repo_root() / "scripts" / "hpc_rsync.sh"
        if not rsync_wrapper.exists():
            raise ConfigError(f"Missing rsync wrapper: {rsync_wrapper}")
        cmd = [
            str(rsync_wrapper),
            "-avz",
            "--partial",
            "--files-from",
            tmp_path,
            f"{local_folder.resolve()}/",
            f"{remote}:{remote_dataset_path.rstrip('/')}/",
        ]
        return _run_command(cmd)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass


def _delete_files_on_remote_with_login(filenames: list[str], remote_login: str) -> int:
    if not filenames:
        print("No remote files selected for deletion.")
        return 0
    bad = [path for path in filenames if not _validate_remote_abs_path(path)]
    if bad:
        raise ConfigError(f"Refusing to delete invalid remote paths: {', '.join(bad)}")
    quoted = " ".join(shlex.quote(path) for path in filenames)
    remote_cmd = f"set -euo pipefail; rm -f -- {quoted}"
    cmd = _remote_shell_cmd(remote_login, remote_cmd)
    return _run_command(cmd)


def delete_files_on_remote(filenames: list[str]) -> int:
    config = _load_hpc_config(None)
    return _delete_files_on_remote_with_login(filenames=filenames, remote_login=config["login"])


def update_dataset(
    dataset_names: list[str], remote: str | None, yes: bool, config_path: Path | None, dry_run: bool = False
) -> int:
    if not dataset_names:
        raise ConfigError("At least one dataset name is required.")
    config = _load_hpc_config(config_path)
    datasets_conf = _dataset_mapping(_load_yaml_mapping(Path(DATASETS_CONF).expanduser()))
    datasets_hpc_conf = _dataset_mapping(_load_yaml_mapping(Path(DATASETS_HPC_CONF).expanduser()))
    remote_login = remote or config["login"]

    for dataset_name in dataset_names:
        local_folder, remote_root, remote_subdir = _resolve_dataset_upload(dataset_name, datasets_conf, datasets_hpc_conf)
        if not local_folder.is_dir():
            raise ConfigError(f"Local folder is not a directory for dataset '{dataset_name}': {local_folder}")

        remote_dataset_path = _dataset_remote_path(remote_root, remote_subdir)
        print(
            f"Update dataset '{dataset_name}': local_folder={local_folder} remote_root={remote_root} remote_subdir={remote_subdir}"
        )

        if not _remote_dir_exists(remote_login, remote_dataset_path):
            print(f"Remote dataset folder missing: {remote_dataset_path}. Fallback to full upload.")
            rc = _run_upload(
                remote=remote_login,
                local_folder=local_folder,
                remote_root=remote_root,
                remote_subdir=remote_subdir,
                yes=yes,
            )
            if rc != 0:
                return rc
            continue

        local_files = _list_local_dataset_files(local_folder)
        remote_files = _list_remote_dataset_files(remote_login, remote_dataset_path)
        selected_upload = sorted(
            rel_path
            for rel_path, local_times in local_files.items()
            if rel_path not in remote_files or local_times["mtime"] > remote_files[rel_path]["mtime"]
        )
        selected_delete_rel = sorted(rel_path for rel_path in (set(remote_files) - set(local_files)))
        bad_delete = [rel_path for rel_path in selected_delete_rel if not _is_safe_rel_sync_path(rel_path)]
        if bad_delete:
            raise ConfigError(f"Refusing delete outside images/lms safe paths: {', '.join(bad_delete)}")
        selected_delete_abs = _to_remote_abs_paths(remote_dataset_path, selected_delete_rel)

        _print_preflight_list("Upload list", selected_upload)
        _print_preflight_list("Delete list", selected_delete_abs)

        if dry_run:
            print("Dry-run enabled: no upload/delete executed.")
            continue

        print(f"Selected {len(selected_upload)} / {len(local_files)} local files for delta upload.")
        rc = _upload_selected_files(
            remote=remote_login,
            local_folder=local_folder,
            remote_root=remote_root,
            remote_subdir=remote_subdir,
            selected_rel_paths=selected_upload,
            yes=yes,
        )
        if rc != 0:
            return rc

        if selected_delete_abs:
            if not yes:
                print("Delete candidates exist but --yes not set. Refusing remote delete; use --dry-run or --yes.")
                return 2
            rc = _delete_files_on_remote_with_login(filenames=selected_delete_abs, remote_login=remote_login)
            if rc != 0:
                return rc
    return 0


def run_dataset_update(
    dataset_names: list[str], remote: str | None, yes: bool, config_path: Path | None, dry_run: bool = False
) -> int:
    return update_dataset(dataset_names=dataset_names, remote=remote, yes=yes, config_path=config_path, dry_run=dry_run)


def _count_files_by_subdir(files: dict[str, FileTimes]) -> tuple[int, int]:
    images = sum(1 for rel_path in files if rel_path.startswith("images/"))
    lms = sum(1 for rel_path in files if rel_path.startswith("lms/"))
    return images, lms


def _poll_dataset_names(dataset_names: list[str], datasets_conf: dict[str, Any], datasets_hpc_conf: dict[str, Any]) -> list[str]:
    if dataset_names:
        return list(dict.fromkeys(dataset_names))
    return sorted(set(datasets_conf) | set(datasets_hpc_conf))


def poll_datasets(dataset_names: list[str], remote: str | None, config_path: Path | None) -> int:
    config = _load_hpc_config(config_path)
    datasets_conf = _dataset_mapping(_load_yaml_mapping(Path(DATASETS_CONF).expanduser()))
    datasets_hpc_conf = _dataset_mapping(_load_yaml_mapping(Path(DATASETS_HPC_CONF).expanduser()))
    remote_login = remote or config["login"]
    names = _poll_dataset_names(dataset_names, datasets_conf, datasets_hpc_conf)

    print(
        "\t".join(
            [
                "dataset",
                "local_images",
                "local_lms",
                "remote_images",
                "remote_lms",
                "missing_remote",
                "missing_local",
                "remote_old",
                "local_old",
                "status",
            ]
        )
    )

    overall_rc = 0
    for dataset_name in names:
        status = "ok"
        local_files: dict[str, FileTimes] = {}
        remote_files: dict[str, FileTimes] = {}
        local_folder: Path | None = None
        remote_root: str | None = None
        remote_subdir: str | None = None

        try:
            if dataset_name in datasets_conf:
                local_folder = _resolve_local_folder_entry(dataset_name, datasets_conf[dataset_name])
            if dataset_name in datasets_hpc_conf:
                remote_root, remote_subdir = _resolve_remote_target_entry(dataset_name, datasets_hpc_conf[dataset_name])
        except ConfigError:
            status = "config_error"
            overall_rc = 1

        if local_folder is None and status == "ok":
            status = "local_cfg_missing"
        elif local_folder is not None and local_folder.is_dir():
            local_files = _list_local_dataset_files(local_folder)
        elif local_folder is not None and status == "ok":
            status = "local_missing"

        if remote_root is None or remote_subdir is None:
            if status == "ok":
                status = "remote_cfg_missing"
        else:
            remote_dataset_path = _dataset_remote_path(remote_root, remote_subdir)
            try:
                remote_exists = _remote_dir_exists(remote_login, remote_dataset_path, verbose=False)
                if remote_exists:
                    remote_files = _list_remote_dataset_files(remote_login, remote_dataset_path, verbose=False)
                elif status == "ok":
                    status = "remote_missing"
            except ConfigError:
                status = "remote_error"
                overall_rc = 1

        local_paths = set(local_files)
        remote_paths = set(remote_files)
        missing_remote = len(local_paths - remote_paths)
        missing_local = len(remote_paths - local_paths)
        overlap = local_paths & remote_paths
        remote_old = sum(1 for rel_path in overlap if local_files[rel_path]["mtime"] > remote_files[rel_path]["mtime"])
        local_old = sum(1 for rel_path in overlap if remote_files[rel_path]["mtime"] > local_files[rel_path]["mtime"])
        if status == "ok" and (missing_remote or missing_local or remote_old or local_old):
            status = "drift"

        local_images, local_lms = _count_files_by_subdir(local_files)
        remote_images, remote_lms = _count_files_by_subdir(remote_files)
        print(
            "\t".join(
                [
                    dataset_name,
                    str(local_images),
                    str(local_lms),
                    str(remote_images),
                    str(remote_lms),
                    str(missing_remote),
                    str(missing_local),
                    str(remote_old),
                    str(local_old),
                    status,
                ]
            )
        )
    return overall_rc


def run_poll_datasets(dataset_names: list[str], remote: str | None, config_path: Path | None) -> int:
    return poll_datasets(dataset_names=dataset_names, remote=remote, config_path=config_path)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hpc-datasets-upload",
        description="Upload datasets by name using $FRAN_CONF/datasets.yaml and $FRAN_CONF/datasets_hpc.yaml.",
    )
    p.add_argument("dataset_names", nargs="*", help="Dataset names in config, e.g. kits23.")
    p.add_argument(
        "--mode",
        choices=("upload", "update_dataset", "poll_datasets"),
        default="upload",
        help="upload = full upload flow, update_dataset = delta update (images/lms), poll_datasets = read-only drift poll.",
    )
    p.add_argument(
        "--remote",
        default=None,
        help="Remote login in user@host form (default: username/host from hpc.yaml).",
    )
    p.add_argument("--config", type=Path, default=None, help="Path to hpc.yaml (default: $FRAN_CONF/hpc.yaml).")
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    p.add_argument("--dry-run", action="store_true", help="For update_dataset: show upload/delete plan only.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "poll_datasets":
            return run_poll_datasets(
                dataset_names=args.dataset_names,
                remote=args.remote,
                config_path=args.config,
            )
        if args.mode == "update_dataset":
            return run_dataset_update(
                dataset_names=args.dataset_names,
                remote=args.remote,
                yes=args.yes,
                config_path=args.config,
                dry_run=args.dry_run,
            )
        return run_dataset_upload(
            dataset_names=args.dataset_names,
            remote=args.remote,
            yes=args.yes,
            config_path=args.config,
        )
    except ConfigError as exc:
        return _print_config_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
