from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from packaging.version import VERSION_PATTERN, Version

DEFAULT_PACKAGES = ("torch", "torchvision", "torchaudio", "torchmetrics", "lightning", "monai", "numpy", "nibabel")
REMOTE_PYTHON = os.environ.get("HPC_ENV_REFRESH_REMOTE_PYTHON", "/data/home/mpx588/.conda/envs/dl/bin/python")
REPO_ROOT = Path(__file__).resolve().parents[1]
SSH_SCRIPT = Path(os.environ.get("HPC_ENV_REFRESH_SSH_SCRIPT", REPO_ROOT / "cli" / "hpc_ssh.sh"))
REMOTE_HELPER = Path(os.environ.get("HPC_ENV_REFRESH_REMOTE_HELPER", REPO_ROOT / "cli" / "env_refresh_remote.sh"))
PIN_TABLE_ENV = "HPC_PIN_TABLE"
DEFAULT_PIN_TABLE = Path("/home/ub/scripts/python_env_setup/install_hpc.py").with_name("hpc_pinned_packages.json")
PIN_TABLE = Path(os.environ[PIN_TABLE_ENV]) if PIN_TABLE_ENV in os.environ else DEFAULT_PIN_TABLE
VERSION_RE = re.compile(f"^{VERSION_PATTERN}$", re.VERBOSE | re.IGNORECASE)


@dataclass(slots=True)
class PackageStatus:
    name: str
    local_version: str
    target_version: str
    remote_version: str
    classification: str
    install_args: list[str]
    spec: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare local vs HPC dl package versions and refresh HPC when it is behind.")
    parser.add_argument(
        "packages",
        nargs="*",
        help="Packages to compare. Defaults to the standard package set plus pinned package names from the shared HPC pin table.",
    )
    parser.add_argument("--check-only", action="store_true", help="Report only. Do not install updates on HPC.")
    return parser.parse_args()


def dedupe_packages(packages: list[str], pinned_packages: dict[str, dict[str, str]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    default_packages = [*DEFAULT_PACKAGES, *[package["name"] for package in pinned_packages.values()]]
    for package in packages or default_packages:
        key = package.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(package)
    return ordered


def installed_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            versions[name.lower()] = dist.version
    return versions


def load_pin_table() -> tuple[list[str], dict[str, dict[str, str]]]:
    table = json.loads(PIN_TABLE.read_text())
    pinned_packages: dict[str, dict[str, str]] = {}
    for package in table["pinned_packages"]:
        pinned_packages[package["name"].lower()] = package
    return table["pip_args"], pinned_packages


def query_remote_versions(packages: list[str]) -> dict[str, str]:
    result = subprocess.run(
        [str(SSH_SCRIPT), "--script", str(REMOTE_HELPER), "--", "query", REMOTE_PYTHON, *packages],
        check=True,
        text=True,
        capture_output=True,
    )
    versions = {package.lower(): "-" for package in packages}
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        package, version = line.split("\t", 1)
        versions[package.lower()] = version
    return versions


def parseable_version(value: str) -> bool:
    return value not in {"", "-"} and VERSION_RE.fullmatch(value) is not None


def classify_package(target_version: str, remote_version: str) -> str:
    if target_version in {"", "-"}:
        return "local_missing"
    if remote_version in {"", "-"}:
        return "remote_missing"
    if not parseable_version(target_version) or not parseable_version(remote_version):
        return "unparseable"
    if Version(remote_version) < Version(target_version):
        return "hpc_behind"
    if Version(remote_version) > Version(target_version):
        return "hpc_ahead"
    return "same"


def classify_pinned_package(target_version: str, remote_version: str) -> str:
    if remote_version in {"", "-"}:
        return "remote_missing"
    if remote_version != target_version:
        return "pinned_mismatch"
    return "same"


def collect_statuses(
    packages: list[str],
    local_versions: dict[str, str],
    remote_versions: dict[str, str],
    pinned_install_args: list[str],
    pinned_packages: dict[str, dict[str, str]],
) -> list[PackageStatus]:
    statuses: list[PackageStatus] = []
    for package in packages:
        package_key = package.lower()
        local_version = local_versions[package_key] if package_key in local_versions else "-"
        remote_version = remote_versions[package_key] if package_key in remote_versions else "-"
        if package_key in pinned_packages:
            target_version = pinned_packages[package_key]["version"]
            install_args = pinned_install_args
            spec = pinned_packages[package_key]["spec"]
            classification = classify_pinned_package(target_version, remote_version)
        else:
            target_version = local_version
            install_args = []
            spec = f"{package}=={local_version}"
            classification = classify_package(target_version, remote_version)
        statuses.append(
            PackageStatus(
                package,
                local_version,
                target_version,
                remote_version,
                classification,
                install_args,
                spec,
            )
        )
    return statuses


def print_statuses(title: str, statuses: list[PackageStatus]) -> None:
    print(title)
    for status in statuses:
        print(
            f"{status.name}: local={status.local_version} target={status.target_version} remote={status.remote_version} status={status.classification}"
        )


def install_remote_args(args: list[str]) -> None:
    subprocess.run(
        [str(SSH_SCRIPT), "--script", str(REMOTE_HELPER), "--", "install", REMOTE_PYTHON, *args],
        check=True,
        text=True,
    )


def apply_updates(statuses: list[PackageStatus]) -> list[str]:
    applied: list[str] = []
    for status in statuses:
        if status.classification not in {"remote_missing", "hpc_behind", "pinned_mismatch"}:
            continue
        install_remote_args([*status.install_args, status.spec])
        applied.append(status.spec)
    return applied


def main() -> int:
    args = parse_args()
    pinned_install_args, pinned_packages = load_pin_table()
    packages = dedupe_packages(args.packages, pinned_packages)
    local_versions = installed_versions()
    remote_versions = query_remote_versions(packages)
    statuses = collect_statuses(packages, local_versions, remote_versions, pinned_install_args, pinned_packages)
    print_statuses("Initial status", statuses)
    if args.check_only:
        print("Check-only mode: no remote updates applied.")
        return 0
    applied = apply_updates(statuses)
    if not applied:
        print("No remote updates needed.")
        return 0
    print("Applied updates")
    for spec in applied:
        print(spec)
    refreshed_remote_versions = query_remote_versions(packages)
    refreshed_statuses = collect_statuses(
        packages,
        local_versions,
        refreshed_remote_versions,
        pinned_install_args,
        pinned_packages,
    )
    print_statuses("Post-update status", refreshed_statuses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
