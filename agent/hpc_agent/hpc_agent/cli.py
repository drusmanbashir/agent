from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_REMOTE_ROOT = "/data/EECS-LITQ/fran_storage/datasets/xnat_shadow"
DEFAULT_REMOTE_LOGIN = "mpx588@login.hpc.qmul.ac.uk"
DEFAULT_LOCAL_BACKUP_ROOT = "/tmp/hpc_agent_backups"


def _menu_prompt(title: str, options: list[str]) -> int:
    print(f"\n{title}")
    for i, opt in enumerate(options, start=1):
        print(f"  {i}) {opt}")
    print("  0) Exit")
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


def _input_required(prompt: str) -> str:
    while True:
        raw = input(f"{prompt}: ").strip()
        if raw:
            return raw
        print("Value cannot be empty.")


def _yes_no(prompt: str, default: bool = True) -> bool:
    default_label = "Y/n" if default else "y/N"
    try:
        raw = input(f"{prompt} ({default_label}): ").strip().lower()
    except EOFError:
        print(f"{prompt} ({default_label}): [EOF -> default {'yes' if default else 'no'}]")
        return default
    if not raw:
        return default
    return raw in {"y", "yes"}


def _run_command(cmd: list[str]) -> int:
    print("Command:")
    print(f"  {shlex.join(cmd)}")
    if not sys.stdin.isatty():
        print("Non-interactive stdin detected; remote password prompts may not be available.")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _build_backup_dir(backup_root: Path, dataset_folder: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = dataset_folder.strip("/").replace("/", "_")
    return backup_root / f"{safe_name}_{stamp}"


def _download_cmd(
    remote: str,
    dataset_folder: str,
    local_dest: Path,
    remote_root: str,
    backup_dir: Path | None,
) -> list[str]:
    remote_path = f"{remote}:{remote_root.rstrip('/')}/{dataset_folder.strip('/')}"
    local_dest.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-avz", "--partial"]
    if backup_dir is not None:
        cmd.extend(["--backup", f"--backup-dir={backup_dir}"])
    cmd.extend([remote_path, str(local_dest)])
    return cmd


def _upload_cmd(
    remote: str,
    local_folder: Path,
    remote_root: str,
    remote_subdir: str | None,
) -> list[str]:
    target_subdir = (remote_subdir or local_folder.name).strip("/")
    remote_path = f"{remote}:{remote_root.rstrip('/')}/{target_subdir}"
    return ["rsync", "-avz", "--partial", str(local_folder), remote_path]


def _run_download(
    remote: str,
    dataset_folder: str,
    local_dest: Path,
    remote_root: str,
    backup_root: Path,
    with_backup: bool,
    yes: bool,
) -> int:
    if not dataset_folder.strip("/"):
        print("Dataset folder cannot be empty.")
        return 2
    target_local = local_dest / Path(dataset_folder.strip("/")).name
    backup_dir: Path | None = None
    if with_backup and target_local.exists():
        backup_dir = _build_backup_dir(backup_root, dataset_folder)
        backup_dir.mkdir(parents=True, exist_ok=True)
        print(f"Backup dir for replaced local files: {backup_dir}")
    cmd = _download_cmd(remote, dataset_folder, local_dest, remote_root, backup_dir)
    if not yes and not _yes_no("Run download now?", default=True):
        print("Cancelled.")
        return 0
    return _run_command(cmd)


def _run_upload(
    remote: str,
    local_folder: Path,
    remote_root: str,
    remote_subdir: str | None,
    yes: bool,
) -> int:
    if not local_folder.exists():
        print(f"Local folder does not exist: {local_folder}")
        return 2
    cmd = _upload_cmd(remote, local_folder, remote_root, remote_subdir)
    if not yes and not _yes_no("Run upload now?", default=True):
        print("Cancelled.")
        return 0
    return _run_command(cmd)


def _run_menu() -> int:
    default_remote = DEFAULT_REMOTE_LOGIN
    default_remote_root = DEFAULT_REMOTE_ROOT
    default_backup_root = DEFAULT_LOCAL_BACKUP_ROOT

    while True:
        choice = _menu_prompt(
            "HPC Data Agent",
            [
                "Download data folder",
                "Upload data folder",
            ],
        )
        if choice == 0:
            return 0

        remote = default_remote
        remote_root = default_remote_root
        backup_root = Path(_input_with_default("Local tmp backup root", default_backup_root)).expanduser()
        with_backup = _input_with_default("Enable local backup for replaced files (y/n)", "y").lower().startswith("y")

        if choice == 1:
            dataset_folder = _input_with_default("Remote subfolder under default data-root", "nodesthick")
            local_dest = Path(_input_required("Local destination folder")).expanduser()
            rc = _run_download(
                remote=remote,
                dataset_folder=dataset_folder,
                local_dest=local_dest,
                remote_root=remote_root,
                backup_root=backup_root,
                with_backup=with_backup,
                yes=False,
            )
        else:
            remote_subdir = _input_with_default("Remote subfolder under default data-root", "nodesthick")
            local_folder = Path(_input_required("Local folder to upload")).expanduser()
            rc = _run_upload(
                remote=remote,
                local_folder=local_folder,
                remote_root=remote_root,
                remote_subdir=remote_subdir,
                yes=False,
            )
        if rc != 0:
            print(f"Transfer command exited with code {rc}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hpc-agent",
        description="Interactive HPC data transfer helper.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("menu", help="Interactive menu.")
    sub.add_parser("dashboard", help="Alias for menu.")

    dln = sub.add_parser("download", help="Download one folder from HPC root to local destination.")
    dln.add_argument(
        "dataset_folder",
        help="Folder name under remote root to download.",
    )
    dln.add_argument("local_dest", type=Path, help="Local destination folder.")
    dln.add_argument(
        "--remote",
        default=DEFAULT_REMOTE_LOGIN,
        help="Remote login in user@host form.",
    )
    dln.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT, help="Remote root folder.")
    dln.add_argument(
        "--backup-root",
        type=Path,
        default=Path(DEFAULT_LOCAL_BACKUP_ROOT),
        help="Local temp backup root for replaced files during download.",
    )
    dln.add_argument(
        "--no-backup",
        action="store_true",
        help="Disable local backup for replaced files.",
    )
    dln.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")

    upl = sub.add_parser("upload", help="Upload one local folder to HPC root.")
    upl.add_argument("local_folder", type=Path, help="Local folder to upload.")
    upl.add_argument(
        "--remote",
        default=DEFAULT_REMOTE_LOGIN,
        help="Remote login in user@host form.",
    )
    upl.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT, help="Remote root folder.")
    upl.add_argument(
        "--remote-subdir",
        default=None,
        help="Destination folder name under remote root (default: local folder name).",
    )
    upl.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd in {"menu", "dashboard"}:
        return _run_menu()
    if args.cmd == "download":
        return _run_download(
            remote=args.remote,
            dataset_folder=args.dataset_folder,
            local_dest=args.local_dest,
            remote_root=args.remote_root,
            backup_root=args.backup_root,
            with_backup=not args.no_backup,
            yes=args.yes,
        )
    if args.cmd == "upload":
        return _run_upload(
            remote=args.remote,
            local_folder=args.local_folder,
            remote_root=args.remote_root,
            remote_subdir=args.remote_subdir,
            yes=args.yes,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
