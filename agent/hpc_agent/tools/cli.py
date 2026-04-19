from __future__ import annotations

import argparse
import json
import os
import posixpath
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CONFIG_ENV = "FRAN_CONF"
CONFIG_NAME = "hpc.yaml"
REMOTE_ROOT_SUBPATH = "datasets/xnat_shadow"
BACKUP_ROOT_ENV = "HPC_AGENT_BACKUP_ROOT"



class ConfigError(RuntimeError):
    pass


def _default_backup_root() -> Path:
    return Path(os.environ.get(BACKUP_ROOT_ENV, "/tmp/hpc_agent_backups")).expanduser()


def _hpc_config_path(config_path: Path | None = None) -> Path:
    if config_path is not None:
        return config_path.expanduser()
    conf_root = os.environ.get(CONFIG_ENV)
    if not conf_root:
        raise ConfigError(f"${CONFIG_ENV} is not set; cannot locate {CONFIG_NAME}.")
    return Path(conf_root).expanduser() / CONFIG_NAME


def _strip_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _fallback_yaml_load(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        if line[:1].isspace() or ":" not in line:
            raise ConfigError(f"Unsupported YAML structure in {path}; install PyYAML for nested YAML.")
        key, value = line.split(":", 1)
        data[key.strip()] = _strip_yaml_scalar(value)
    return data


def _load_hpc_config(config_path: Path | None = None) -> dict[str, str]:
    path = _hpc_config_path(config_path)
    if not path.exists():
        raise ConfigError(f"HPC config not found: {path}")
    try:
        import yaml  # type: ignore
    except Exception:
        raw = _fallback_yaml_load(path)
    else:
        loaded = yaml.safe_load(path.read_text())
        if not isinstance(loaded, dict):
            raise ConfigError(f"HPC config must be a mapping: {path}")
        raw = {str(k): "" if v is None else str(v) for k, v in loaded.items()}

    required = ("host", "username", "password", "hpc_storage", "hpc_conf")
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ConfigError(f"Missing required HPC config keys in {path}: {', '.join(missing)}")

    hpc_conf_parent = posixpath.dirname(raw["hpc_conf"].rstrip("/"))
    data = {
        "config_path": str(path),
        "host": raw["host"],
        "username": raw["username"],
        "password": raw["password"],
        "login": f"{raw['username']}@{raw['host']}",
        "hpc_storage": raw["hpc_storage"],
        "hpc_conf": raw["hpc_conf"],
        "xnat_shadow_root": posixpath.join(hpc_conf_parent, REMOTE_ROOT_SUBPATH),
        "local_backup_root": str(_default_backup_root()),
    }
    return data


def _redacted_hpc_config(config: dict[str, str]) -> dict[str, str]:
    redacted = dict(config)
    if redacted.get("password"):
        redacted["password"] = "<REDACTED>"
    return redacted


def _print_config_error(exc: ConfigError) -> int:
    print(f"Config error: {exc}", file=sys.stderr)
    return 2


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


def _run_menu(config_path: Path | None = None) -> int:
    try:
        config = _load_hpc_config(config_path)
    except ConfigError as exc:
        return _print_config_error(exc)
    default_remote = config["login"]
    default_remote_root = config["xnat_shadow_root"]
    default_backup_root = config["local_backup_root"]

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
            dataset_folder = _input_required("Remote subfolder under default data-root")
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
            remote_subdir = _input_required("Remote subfolder under default data-root")
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


def _run_load_pwd(
    config_path: Path | None,
    field: str | None,
    show_password: bool,
    output_format: str,
) -> int:
    try:
        config = _load_hpc_config(config_path)
    except ConfigError as exc:
        return _print_config_error(exc)

    visible_config = config if show_password else _redacted_hpc_config(config)
    if field:
        if field not in config:
            print(f"Unknown field: {field}", file=sys.stderr)
            print(f"Available fields: {', '.join(sorted(config))}", file=sys.stderr)
            return 2
        if field == "password" and not show_password:
            print("Refusing to print password without --show-password.", file=sys.stderr)
            return 2
        print(config[field])
        return 0

    if output_format == "json":
        print(json.dumps(visible_config, indent=2, sort_keys=True))
        return 0
    if output_format == "shell":
        for key, value in visible_config.items():
            env_key = f"HPC_{key.upper()}"
            print(f"export {env_key}={shlex.quote(value)}")
        return 0
    for key, value in visible_config.items():
        print(f"{key}: {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hpc-agent",
        description="Interactive HPC data transfer helper.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    menu = sub.add_parser("menu", help="Interactive menu.")
    menu.add_argument("--config", type=Path, default=None, help="Path to hpc.yaml (default: $FRAN_CONF/hpc.yaml).")

    dashboard = sub.add_parser("dashboard", help="Alias for menu.")
    dashboard.add_argument("--config", type=Path, default=None, help="Path to hpc.yaml (default: $FRAN_CONF/hpc.yaml).")

    load_pwd = sub.add_parser("load_pwd", help="Load HPC details from $FRAN_CONF/hpc.yaml.")
    load_pwd.add_argument("--config", type=Path, default=None, help="Path to hpc.yaml (default: $FRAN_CONF/hpc.yaml).")
    load_pwd.add_argument(
        "--field",
        default=None,
        help="Print one field only, such as host, username, login, password, hpc_storage, hpc_conf, or xnat_shadow_root.",
    )
    load_pwd.add_argument(
        "--show-password",
        action="store_true",
        help="Allow password output. Without this, password is redacted and --field password is refused.",
    )
    load_pwd.add_argument(
        "--format",
        choices=("json", "shell", "plain"),
        default="json",
        help="Output format for all fields.",
    )

    dln = sub.add_parser("download", help="Download one folder from HPC root to local destination.")
    dln.add_argument(
        "dataset_folder",
        help="Folder name under remote root to download.",
    )
    dln.add_argument("local_dest", type=Path, help="Local destination folder.")
    dln.add_argument(
        "--remote",
        default=None,
        help="Remote login in user@host form (default: username/host from hpc.yaml).",
    )
    dln.add_argument("--remote-root", default=None, help="Remote root folder (default: derived from hpc_conf in hpc.yaml).")
    dln.add_argument("--config", type=Path, default=None, help="Path to hpc.yaml (default: $FRAN_CONF/hpc.yaml).")
    dln.add_argument(
        "--backup-root",
        type=Path,
        default=None,
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
        default=None,
        help="Remote login in user@host form (default: username/host from hpc.yaml).",
    )
    upl.add_argument("--remote-root", default=None, help="Remote root folder (default: derived from hpc_conf in hpc.yaml).")
    upl.add_argument("--config", type=Path, default=None, help="Path to hpc.yaml (default: $FRAN_CONF/hpc.yaml).")
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
        return _run_menu(args.config)
    if args.cmd == "load_pwd":
        return _run_load_pwd(
            config_path=args.config,
            field=args.field,
            show_password=args.show_password,
            output_format=args.format,
        )
    if args.cmd == "download":
        try:
            config = _load_hpc_config(args.config)
        except ConfigError as exc:
            return _print_config_error(exc)
        return _run_download(
            remote=args.remote or config["login"],
            dataset_folder=args.dataset_folder,
            local_dest=args.local_dest,
            remote_root=args.remote_root or config["xnat_shadow_root"],
            backup_root=args.backup_root or Path(config["local_backup_root"]),
            with_backup=not args.no_backup,
            yes=args.yes,
        )
    if args.cmd == "upload":
        try:
            config = _load_hpc_config(args.config)
        except ConfigError as exc:
            return _print_config_error(exc)
        return _run_upload(
            remote=args.remote or config["login"],
            local_folder=args.local_folder,
            remote_root=args.remote_root or config["xnat_shadow_root"],
            remote_subdir=args.remote_subdir,
            yes=args.yes,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
