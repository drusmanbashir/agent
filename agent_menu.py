from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent


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


def _run_in_folder(folder: Path, args: list[str]) -> int:
    if not folder.exists():
        print(f"Missing folder: {folder}")
        return 2
    print(f"\nLaunching: {' '.join(args)}")
    print(f"Working directory: {folder}\n")
    proc = subprocess.run(args, cwd=str(folder), check=False)
    return proc.returncode


def main() -> int:
    options = [
        "XNAT DICOM Agent UI",
        "HPC Data Transfer Agent UI",
        "Gmail Agent UI",
        "Agent Hub Web UI",
    ]

    while True:
        choice = _menu_prompt("Grand Agent Menu", options)
        if choice == 0:
            return 0

        if choice == 1:
            rc = _run_in_folder(
                REPO_ROOT / "agent" / "dicom_xnat_agent",
                [sys.executable, "-m", "dicom_xnat_agent.cli", "menu"],
            )
        elif choice == 2:
            rc = _run_in_folder(
                REPO_ROOT / "agent" / "hpc_agent",
                [sys.executable, "-m", "hpc_agent.cli", "menu"],
            )
        elif choice == 3:
            rc = _run_in_folder(
                REPO_ROOT / "agent" / "gmail_agent",
                [sys.executable, "-m", "agent.cli", "menu"],
            )
        else:
            rc = _run_in_folder(
                REPO_ROOT,
                [sys.executable, "agent_hub.py"],
            )

        if rc != 0:
            print(f"Selected agent exited with code {rc}.")


if __name__ == "__main__":
    raise SystemExit(main())
