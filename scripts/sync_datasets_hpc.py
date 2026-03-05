"""Sync source datasets to their HPC storage paths using rsync."""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def build_dataset_map(cfg: dict, file_path: Path) -> dict[str, dict]:
    data = cfg.get("datasets")
    if not isinstance(data, dict):
        raise ValueError(f"{file_path} must contain a `datasets` map.")
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync every source dataset folder listed in datasets.yaml to its"
                    " counterpart on the HPC filesystem using rsync.")
    parser.add_argument(
        "--conf-dir",
        type=Path,
        default=Path("/s/fran_storage/conf"),
        help="Directory that holds datasets.yaml, datasets_hpc.yaml, and hpc.yaml.")
    parser.add_argument(
        "--datasets",
        nargs="+",
        help="Optional list of dataset names to sync. Defaults to every dataset present"
             " in both config files.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show rsync commands without copying files.")
    parser.add_argument(
        "--ssh-command",
        default="ssh",
        help="Command to pass to rsync's -e option. Use this to inject custom ssh flags.")
    parser.add_argument(
        "--no-ssh-multiplex",
        action="store_true",
        help="Disable SSH connection multiplexing across rsync calls.")
    parser.add_argument(
        "--ssh-control-path",
        default="/tmp/codex_ssh_mux/%r@%h:%p",
        help="SSH multiplex control socket path used when multiplexing is enabled.")
    parser.add_argument(
        "--ssh-control-persist",
        default="10m",
        help="SSH ControlPersist duration when multiplexing is enabled.")
    parser.add_argument(
        "--rsync-extra-opts",
        default="",
        help="Additional rsync options to append (e.g. '--compress-level=0').")
    parser.add_argument(
        "--host",
        help="Override hpc.yaml host value.")
    parser.add_argument(
        "--username",
        help="Override hpc.yaml username value.")
    return parser.parse_args()


def _build_rsync_ssh_command(args: argparse.Namespace) -> str:
    ssh_parts = shlex.split(args.ssh_command)
    if args.no_ssh_multiplex:
        return shlex.join(ssh_parts)

    control_path = os.path.expanduser(args.ssh_control_path)
    control_parent = Path(control_path).expanduser().parent
    control_parent.mkdir(parents=True, exist_ok=True)

    ssh_parts.extend(
        [
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPersist={args.ssh_control_persist}",
            "-o",
            f"ControlPath={control_path}",
        ]
    )
    return shlex.join(ssh_parts)


def _ensure_remote_dir(
    ssh_command: str,
    username: str,
    host: str,
    remote_dir: str,
    dry_run: bool,
) -> None:
    if dry_run:
        logging.info("Dry-run: would ensure remote dir exists: %s", remote_dir)
        return
    mkdir_cmd = shlex.join(["mkdir", "-p", remote_dir])
    cmd = [*shlex.split(ssh_command), f"{username}@{host}", mkdir_cmd]
    subprocess.run(cmd, check=True)


def _sync_conf_files_to_hpc(
    conf_dir: Path,
    base_cmd: list[str],
    ssh_command: str,
    username: str,
    host: str,
    hpc_conf_dir: str,
    dry_run: bool,
) -> None:
    print("\033[1m[INFO] Sending conf files to HPC...\033[0m")
    _ensure_remote_dir(
        ssh_command=ssh_command,
        username=username,
        host=host,
        remote_dir=hpc_conf_dir,
        dry_run=dry_run,
    )

    conf_transfers = [
        (conf_dir / "datasets_hpc.yaml", "datasets.yaml"),
        (conf_dir / "config_hpc.yaml", "config.yaml"),
    ]
    conf_cmd_base = [arg for arg in base_cmd if arg != "--ignore-existing"]

    for local_conf, remote_name in conf_transfers:
        if not local_conf.is_file():
            raise FileNotFoundError(f"Missing required conf file: {local_conf}")
        dest_arg = f"{username}@{host}:{hpc_conf_dir.rstrip('/')}/{remote_name}"
        cmd = [*conf_cmd_base, str(local_conf), dest_arg]
        logging.info("Syncing conf %s -> %s", local_conf, dest_arg)
        subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    conf_dir = args.conf_dir.resolve()
    local_path = conf_dir / "datasets.yaml"
    hpc_path = conf_dir / "datasets_hpc.yaml"
    hpc_config_path = conf_dir / "hpc.yaml"
    for path in (local_path, hpc_path, hpc_config_path):
        if not path.is_file():
            logging.error("Missing configuration file: %s", path)
            return 1

    local_cfg = build_dataset_map(load_yaml(local_path), local_path)
    hpc_cfg = build_dataset_map(load_yaml(hpc_path), hpc_path)
    hpc_connection = load_yaml(hpc_config_path)

    host = args.host or hpc_connection.get("host")
    username = args.username or hpc_connection.get("username")
    if not host or not username:
        logging.error("HPC host and username must be configured in hpc.yaml or via CLI.")
        return 1
    hpc_conf_dir = hpc_connection.get("hpc_conf")
    if not hpc_conf_dir:
        logging.error("hpc.yaml must include `hpc_conf` for remote conf sync.")
        return 1

    requested = args.datasets
    dataset_names: list[str] = []
    if requested:
        for name in requested:
            if name not in local_cfg:
                logging.warning("Skipping %s because it is missing from datasets.yaml", name)
                continue
            if name not in hpc_cfg:
                logging.warning("Skipping %s because it is missing from datasets_hpc.yaml", name)
                continue
            dataset_names.append(name)
    else:
        dataset_names = sorted(set(local_cfg) & set(hpc_cfg))

    if not dataset_names:
        logging.info("No datasets to sync after filtering. Exiting.")
        return 0

    base_cmd = [
        "rsync",
        "--archive",
        "--compress",
        "--ignore-existing",
        "--partial",
        "--progress",
    ]
    if args.dry_run:
        base_cmd.append("--dry-run")
    ssh_command = _build_rsync_ssh_command(args)
    if ssh_command:
        base_cmd.extend(["-e", ssh_command])
    if args.rsync_extra_opts:
        base_cmd.extend(shlex.split(args.rsync_extra_opts))

    for name in dataset_names:
        local_entry = local_cfg[name]
        hpc_entry = hpc_cfg[name]
        local_folder = local_entry.get("folder")
        remote_folder = hpc_entry.get("folder")
        if not local_folder or not remote_folder:
            logging.warning("Skipping %s because one of the folders is missing", name)
            continue

        local_dir = Path(local_folder).expanduser()
        if not local_dir.exists():
            logging.warning("Local folder not found for %s: %s", name, local_dir)
            continue

        remote_dir = remote_folder.rstrip("/")
        if not remote_dir:
            logging.warning("Remote folder is empty for %s", name)
            continue
        try:
            _ensure_remote_dir(
                ssh_command=ssh_command,
                username=username,
                host=host,
                remote_dir=remote_dir,
                dry_run=args.dry_run,
            )
        except subprocess.CalledProcessError as exc:
            logging.error("Failed to create remote directory %s (%s)", remote_dir, exc)
            return 1

        destinations = [
            (local_dir / "images", True),
            (local_dir / "lms", True),
            (local_dir / "fg_voxels.h5", False),
        ]

        for local_source, is_dir in destinations:
            if not local_source.exists():
                logging.debug("Skipping missing entry %s for dataset %s", local_source, name)
                continue
            if is_dir and not local_source.is_dir():
                logging.warning("Expected directory %s for dataset %s", local_source, name)
                continue
            if not is_dir and not local_source.is_file():
                logging.warning("Expected file %s for dataset %s", local_source, name)
                continue

            remote_subpath = f"{remote_dir}/{local_source.name}"
            if is_dir:
                source_arg = f"{local_source}/"
                dest_arg = f"{username}@{host}:{remote_subpath}/"
            else:
                source_arg = str(local_source)
                dest_arg = f"{username}@{host}:{remote_subpath}"

            cmd = [*base_cmd, source_arg, dest_arg]
            logging.info("Syncing %s -> %s", source_arg, dest_arg)
            logging.debug("Command: %s", cmd)
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as exc:
                logging.error("Failed to rsync %s (%s)", local_source, exc)
                return 1

    try:
        _sync_conf_files_to_hpc(
            conf_dir=conf_dir,
            base_cmd=base_cmd,
            ssh_command=ssh_command,
            username=username,
            host=host,
            hpc_conf_dir=hpc_conf_dir,
            dry_run=args.dry_run,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logging.error("Failed to sync conf files to HPC (%s)", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
