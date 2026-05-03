from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import shlex
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
import yaml

from tools.cli import ConfigError, _load_hpc_config, _map_local_path_to_hpc_path, _yes_no
from tools.datasets import (
    _is_safe_rel_sync_path,
    _list_local_dataset_files,
    _list_remote_dataset_files,
    _remote_dir_exists,
    _remote_shell_cmd,
    _repo_root,
)

SYNC_SUBDIRS = ("images", "lms")
CONF_SYNC = (
    ("datasets_hpc.yaml", "datasets.yaml"),
    ("config_hpc.yaml", "config.yaml"),
    ("best_runs.yaml", "best_runs.yaml"),
    ("sinclair_hpc_path_mapping.yaml", "sinclair_hpc_path_mapping.yaml"),
)
LOCAL_HPC_REPOS = ("fran", "localiser", "utilz", "label_analysis")


LOCAL_COLD_STORAGE_ENV = "COLD_STORAGE"


def _code_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _conf_dir() -> Path:
    cold_storage = Path(os.environ[LOCAL_COLD_STORAGE_ENV]).expanduser()
    return cold_storage / "conf"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(cmd: list[str], dry_run: bool) -> int:
    print(f"CMD {shlex.join(cmd)}")
    if dry_run:
        return 0
    return subprocess.run(cmd, check=False).returncode


def _capture(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    print(f"CMD {shlex.join(cmd)}")
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _local_repo_root(name: str) -> Path:
    return _code_root() / name


def _local_repo_branch(repo: Path) -> str:
    proc = _capture(["git", "-C", str(repo), "branch", "--show-current"])
    if proc.returncode != 0:
        raise ConfigError(proc.stderr.strip() or f"failed branch lookup: {repo}")
    branch = proc.stdout.strip()
    if not branch:
        raise ConfigError(f"empty branch for repo: {repo}")
    return branch


def _local_repo_dirty(repo: Path) -> bool:
    proc = _capture(["git", "-C", str(repo), "status", "--short"])
    if proc.returncode != 0:
        raise ConfigError(proc.stderr.strip() or f"failed status: {repo}")
    return bool(proc.stdout.strip())


def _sync_local_repo(repo: Path, branch: str, dry_run: bool) -> int:
    dirty = _local_repo_dirty(repo)
    if dirty:
        rc = _run(["git", "-C", str(repo), "add", "-A"], dry_run)
        if rc != 0:
            return rc
        rc = _run(
            ["git", "-C", str(repo), "commit", "-m", f"hpc_refresh sync {_stamp()}"],
            dry_run,
        )
        if rc != 0:
            return rc
    return _run(["git", "-C", str(repo), "push", "-u", "origin", branch], dry_run)


def _sync_local_repos(branch: str, dry_run: bool) -> int:
    for name in LOCAL_HPC_REPOS:
        repo = _local_repo_root(name)
        if not repo.is_dir():
            print(f"SKIP missing local repo: {repo}")
            continue
        if not (repo / ".git").exists():
            print(f"SKIP non-git local repo: {repo}")
            continue
        print(f"=== LOCAL REPO {repo} ===")
        repo_branch = _local_repo_branch(repo)
        if repo_branch != branch:
            print(f"WARN branch mismatch local={repo_branch} requested={branch}; pushing current local branch")
        rc = _sync_local_repo(repo, repo_branch, dry_run)
        if rc != 0:
            return rc
    return 0


def _remote_capture(remote: str, remote_cmd: str) -> subprocess.CompletedProcess[str]:
    return _capture(_remote_shell_cmd(remote, remote_cmd))


def _ensure_remote_dir(remote: str, remote_dir: str, dry_run: bool) -> int:
    return _run(_remote_shell_cmd(remote, f"mkdir -p {shlex.quote(remote_dir)}"), dry_run)


def _remote_file_hash(remote: str, remote_path: str) -> str:
    cmd = (
        f"if [ -f {shlex.quote(remote_path)} ]; then "
        f"sha256sum {shlex.quote(remote_path)} | awk '{{print $1}}'; "
        "fi"
    )
    proc = _remote_capture(remote, cmd)
    if proc.returncode != 0:
        raise ConfigError(proc.stderr.strip() or f"failed remote hash for {remote_path}")
    return proc.stdout.strip()


def _rsync_to_remote(remote: str, local_path: Path, remote_path: str, dry_run: bool) -> int:
    rsync = _repo_root() / "cli" / "hpc_rsync.sh"
    cmd = [str(rsync), "-avz", "--partial"]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend([str(local_path), f"{remote}:{remote_path}"])
    return _run(cmd, dry_run=False)


def _replace_remote_file(remote: str, local_path: Path, remote_path: str, dry_run: bool) -> int:
    local_hash = _sha256_path(local_path)
    remote_hash = _remote_file_hash(remote, remote_path)
    if local_hash == remote_hash:
        print(f"SKIP {remote_path}")
        return 0
    parent = posixpath.dirname(remote_path)
    tmp_path = f"{remote_path}.refresh_tmp_{_stamp()}"
    backup_path = f"{remote_path}.refresh_bak_{_stamp()}"
    rc = _ensure_remote_dir(remote, parent, dry_run)
    if rc != 0:
        return rc
    rc = _rsync_to_remote(remote, local_path, tmp_path, dry_run)
    if rc != 0:
        return rc
    remote_cmd = (
        f"set -euo pipefail; "
        f"if [ -f {shlex.quote(remote_path)} ]; then "
        f"cp -p {shlex.quote(remote_path)} {shlex.quote(backup_path)}; "
        f"echo BACKUP {shlex.quote(remote_path)} '->' {shlex.quote(backup_path)}; "
        f"fi; "
        f"mv {shlex.quote(tmp_path)} {shlex.quote(remote_path)}; "
        f"echo REPLACE {shlex.quote(tmp_path)} '->' {shlex.quote(remote_path)}"
    )
    return _run(_remote_shell_cmd(remote, remote_cmd), dry_run)


def _load_dataset_map(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text())
    if isinstance(data, dict) and "datasets" in data:
        nested = data["datasets"]
        if isinstance(nested, dict):
            return nested
    if isinstance(data, dict):
        return data
    raise ConfigError(f"datasets map must be dict: {path}")


def _load_dataset_map_text(text: str, source: str) -> dict[str, object]:
    data = yaml.safe_load(text)
    if isinstance(data, dict) and "datasets" in data:
        nested = data["datasets"]
        if isinstance(nested, dict):
            return nested
    if isinstance(data, dict):
        return data
    raise ConfigError(f"datasets map must be dict: {source}")


def _dataset_path(dataset_name: str, entry: object, keys: tuple[str, ...]) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if not isinstance(entry, dict):
        raise ConfigError(f"dataset entry must be str/dict: {dataset_name}")
    for key in keys:
        if key in entry and isinstance(entry[key], str) and entry[key].strip():
            return entry[key].strip()
    raise ConfigError(f"dataset path missing for {dataset_name}")


def _dataset_names(local_map: dict[str, object], remote_map: dict[str, object], names: list[str]) -> list[str]:
    if names:
        return list(dict.fromkeys(names))
    missing_local = sorted(set(remote_map) - set(local_map))
    missing_remote = sorted(set(local_map) - set(remote_map))
    if missing_local:
        print(f"SKIP remote-only datasets: {', '.join(missing_local)}")
    if missing_remote:
        print(f"SKIP local-only datasets: {', '.join(missing_remote)}")
    return sorted(set(local_map) & set(remote_map))


def _print_rel_list(label: str, paths: list[str]) -> None:
    print(f"{label} {len(paths)}")
    for rel_path in paths:
        print(rel_path)


def _print_dataset_plan(
    dataset_name: str,
    local_root: Path,
    remote_root: str,
    archive_root: str,
    upload_missing_rel: list[str],
    upload_stale_rel: list[str],
    move_rel: list[str],
    remote_newer: list[str],
) -> None:
    print(f"=== DATASET {dataset_name} ===")
    print(f"LOCAL  {local_root}")
    print(f"REMOTE {remote_root}")
    print(f"ARCHIVE_DEST_BASE {archive_root}")
    _print_rel_list("MISSING_REMOTE", upload_missing_rel)
    _print_rel_list("STALE_REMOTE_OLDER", upload_stale_rel)
    _print_rel_list("UPLOAD_OR_OVERWRITE", upload_missing_rel + upload_stale_rel)
    _print_rel_list("EXTRA_NOT_LOCAL", move_rel)
    _print_rel_list("REMOTE_NEWER_KEEP", remote_newer)


def _confirm_dataset_apply(dataset_name: str) -> bool:
    reply = input(f"Apply remote changes for dataset {dataset_name}? (y/n): ").strip().lower()
    return reply in {"y", "yes"}


def _upload_rel_paths(remote: str, local_root: Path, remote_root: str, rel_paths: list[str], dry_run: bool) -> int:
    if not rel_paths:
        return 0
    rc = _ensure_remote_dir(remote, remote_root, dry_run)
    if rc != 0:
        return rc
    for subdir in SYNC_SUBDIRS:
        rc = _ensure_remote_dir(remote, f"{remote_root.rstrip('/')}/{subdir}", dry_run)
        if rc != 0:
            return rc
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        for rel_path in rel_paths:
            handle.write(f"{rel_path}\n")
        files_from = handle.name
    rsync = _repo_root() / "cli" / "hpc_rsync.sh"
    cmd = [str(rsync), "-avz", "--partial", "--files-from", files_from]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend([f"{local_root.resolve()}/", f"{remote}:{remote_root.rstrip('/')}/"])
    rc = _run(cmd, dry_run=False)
    Path(files_from).unlink()
    return rc


def _dataset_archive_root(cold_storage: str, dataset_name: str, stamp: str) -> str:
    return f"{cold_storage.rstrip('/')}/datasets/archived/{dataset_name}/{stamp}"


def _move_remote_extras(
    remote: str,
    cold_storage: str,
    dataset_name: str,
    remote_root: str,
    rel_paths: list[str],
    dry_run: bool,
) -> int:
    if not rel_paths:
        return 0
    stamp = _stamp()
    archive_root = _dataset_archive_root(cold_storage, dataset_name, stamp)
    for rel_path in rel_paths:
        src = f"{remote_root.rstrip('/')}/{rel_path}"
        dest = f"{archive_root}/{rel_path}"
        remote_cmd = (
            "set -euo pipefail; "
            f"mkdir -p {shlex.quote(posixpath.dirname(dest))}; "
            f"echo MOVE {shlex.quote(src)} '->' {shlex.quote(dest)}; "
            f"mv {shlex.quote(src)} {shlex.quote(dest)}"
        )
        rc = _run(_remote_shell_cmd(remote, remote_cmd), dry_run)
        if rc != 0:
            return rc
    return 0


def _remote_cold_storage(local_cold_storage: Path) -> str:
    return _map_local_path_to_hpc_path(str(local_cold_storage)).rstrip("/")


def _refresh_git(remote: str, cold_storage: str, branch: str, dry_run: bool) -> int:
    script = _repo_root() / "cli" / "git_all.sh"
    cmd = [str(_repo_root() / "cli" / "hpc_ssh.sh"), "--login", remote, "--script", str(script), "--", "--cold-storage", cold_storage, branch]
    return _run(cmd, dry_run)


def _refresh_conf(remote: str, conf_dir: Path, remote_conf_dir: str, dry_run: bool) -> int:
    for local_name, remote_name in CONF_SYNC:
        rc = _replace_remote_file(remote, conf_dir / local_name, f"{remote_conf_dir.rstrip('/')}/{remote_name}", dry_run)
        if rc != 0:
            return rc
    return 0


def _refresh_project_status(remote: str, cold_storage: str, dry_run: bool) -> int:
    local_path = _code_root() / "fran" / "fran" / "run" / "project" / "project_status.py"
    remote_path = f"{cold_storage}/code/fran/fran/run/project/project_status.py"
    return _replace_remote_file(remote, local_path, remote_path, dry_run)


def _sync_datasets(remote: str, conf_dir: Path, cold_storage: str, dataset_names: list[str], dry_run: bool) -> int:
    local_map = _load_dataset_map(conf_dir / "datasets.yaml")
    remote_map_path = f"{cold_storage}/conf/datasets.yaml"
    proc = _remote_capture(remote, f"cat {shlex.quote(remote_map_path)}")
    if proc.returncode != 0:
        raise ConfigError(proc.stderr.strip() or f"failed remote read: {remote_map_path}")
    remote_map = _load_dataset_map_text(proc.stdout, remote_map_path)
    names = _dataset_names(local_map, remote_map, dataset_names)
    for dataset_name in names:
        if dataset_name not in local_map or dataset_name not in remote_map:
            raise ConfigError(f"dataset missing from one map: {dataset_name}")
        local_root = Path(_dataset_path(dataset_name, local_map[dataset_name], ("local_folder", "folder", "path"))).expanduser()
        remote_root = _dataset_path(dataset_name, remote_map[dataset_name], ("remote_path", "folder", "path", "remote_folder"))
        if not local_root.is_dir():
            raise ConfigError(f"local dataset folder missing: {local_root}")
        if not remote_root.startswith("/"):
            raise ConfigError(f"remote dataset folder must be absolute: {dataset_name} -> {remote_root}")
        local_files = _list_local_dataset_files(local_root)
        remote_files = {}
        if _remote_dir_exists(remote, remote_root, verbose=False):
            remote_files = _list_remote_dataset_files(remote, remote_root, verbose=False)
        upload_missing_rel = sorted(rel_path for rel_path in local_files if rel_path not in remote_files)
        upload_stale_rel = sorted(
            rel_path
            for rel_path in local_files
            if rel_path in remote_files and local_files[rel_path]["mtime"] > remote_files[rel_path]["mtime"]
        )
        upload_rel = upload_missing_rel + upload_stale_rel
        move_rel = sorted(rel_path for rel_path in remote_files if rel_path not in local_files)
        remote_newer = sorted(
            rel_path
            for rel_path in local_files
            if rel_path in remote_files and remote_files[rel_path]["mtime"] > local_files[rel_path]["mtime"]
        )
        archive_root = _dataset_archive_root(cold_storage, dataset_name, "YYYYmmdd_HHMMSS")
        bad = [rel_path for rel_path in move_rel if not _is_safe_rel_sync_path(rel_path)]
        if bad:
            raise ConfigError(f"unsafe remote path(s) for {dataset_name}: {', '.join(bad)}")
        _print_dataset_plan(
            dataset_name=dataset_name,
            local_root=local_root,
            remote_root=remote_root,
            archive_root=archive_root,
            upload_missing_rel=upload_missing_rel,
            upload_stale_rel=upload_stale_rel,
            move_rel=move_rel,
            remote_newer=remote_newer,
        )
        if not upload_rel and not move_rel:
            print(f"NO_CHANGES {dataset_name}")
            continue
        if dry_run:
            print(f"DRY_RUN_SKIP_MUTATION {dataset_name}")
            continue
        if not _confirm_dataset_apply(dataset_name):
            print(f"SKIP_MUTATION {dataset_name}")
            continue
        rc = _upload_rel_paths(remote, local_root, remote_root, upload_rel, dry_run)
        if rc != 0:
            return rc
        rc = _move_remote_extras(remote, cold_storage, dataset_name, remote_root, move_rel, dry_run)
        if rc != 0:
            return rc
    return 0


def main(args: argparse.Namespace) -> int:
    config = _load_hpc_config(args.config)
    remote = args.remote or config["login"]
    local_cold_storage = Path(os.environ[LOCAL_COLD_STORAGE_ENV]).expanduser()
    conf_dir = _conf_dir()
    cold_storage = _remote_cold_storage(local_cold_storage)
    if not args.yes and not args.dry_run:
        if not _yes_no("Run HPC refresh now?", default=True):
            print("Cancelled.")
            return 0
    rc = _sync_local_repos(args.branch, args.dry_run)
    if rc != 0:
        return rc
    rc = _refresh_git(remote, cold_storage, args.branch, args.dry_run)
    if rc != 0:
        return rc
    rc = _refresh_conf(remote, conf_dir, config["hpc_conf"], args.dry_run)
    if rc != 0:
        return rc
    rc = _refresh_project_status(remote, cold_storage, args.dry_run)
    if rc != 0:
        return rc
    return _sync_datasets(remote, conf_dir, cold_storage, args.dataset_names, args.dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh HPC repos, config files, package file, and dataset trees.")
    parser.add_argument("dataset_names", nargs="*", help="Optional dataset names from datasets.yaml.")
    parser.add_argument("--config", type=Path, default=None, help="Path to hpc.yaml (default: $FRAN_CONF/hpc.yaml).")
    parser.add_argument("--remote", default=None, help="Remote login in user@host form.")
    parser.add_argument("--branch", default="main", help="Git branch for repo refresh.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without mutating remote files.")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    args = parser.parse_known_args()[0]
    raise SystemExit(main(args))
