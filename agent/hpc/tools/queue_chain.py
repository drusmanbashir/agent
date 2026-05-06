from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _hpc_ssh_script() -> Path:
    return _repo_root() / "cli" / "hpc_ssh.sh"


def _job_registry_script() -> Path:
    return _repo_root() / "cli" / "job_registry.sh"


def _remote_queue_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

prefix="$1"
log_dir="$2"
partition="$3"
ntasks="$4"
cpus_per_task="$5"
time_limit="$6"
mem_per_cpu="$7"
mail_type="$8"
dry_run="$9"
shift 9

commands=("$@")
dep_job=""
idx=0

for cmd in "${commands[@]}"; do
  idx=$((idx + 1))
  job_name="${prefix}_${idx}"
  sb=(
    sbatch
    --parsable
    -J "$job_name"
    -D "$log_dir"
    -p "$partition"
    -n "$ntasks"
    --cpus-per-task="$cpus_per_task"
    -t "$time_limit"
    --mem-per-cpu="$mem_per_cpu"
    -o "$log_dir/%x-%j.out"
    -e "$log_dir/%x-%j.err"
  )
  if [[ -n "$dep_job" ]]; then
    sb+=(--dependency "afterok:${dep_job}")
  fi
  if [[ "$mail_type" != "NONE" ]]; then
    sb+=(--mail-type "$mail_type")
  fi
  sb+=(--wrap "$cmd")

  echo "queue_${idx}_cmd=${cmd}"
  echo "queue_${idx}_sbatch=${sb[*]}"

  if [[ "$dry_run" == "1" ]]; then
    dep_job="DRYRUN_${idx}"
    echo "queue_${idx}_job=${dep_job}"
    continue
  fi

  jid="$("${sb[@]}" | awk -F';' '{print $1}')"
  dep_job="$jid"
  echo "queue_${idx}_job=${jid}"
done

echo "queue_count=${idx}"
echo "last_job=${dep_job}"
"""


def _register_jobs(output: str, job_name_prefix: str, script_path: Path) -> None:
    registry_script = _job_registry_script()
    submitter_path = Path(__file__).resolve()
    for line in output.splitlines():
        if not line.startswith("queue_") or "_job=" not in line:
            continue
        key, job_id = line.split("=", 1)
        if not job_id or job_id.startswith("DRYRUN_"):
            continue
        idx = key.split("_", 2)[1]
        subprocess.run(
            [
                str(registry_script),
                "submit",
                job_id,
                str(submitter_path),
                f"{job_name_prefix}_{idx}",
                f"stdin:{script_path}",
            ],
            check=True,
        )


def main(args: argparse.Namespace) -> int:
    remote_script = _remote_queue_script()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(remote_script)
        script_path = Path(handle.name)
    script_path.chmod(0o755)

    try:
        cmd = [str(_hpc_ssh_script())]
        if args.login:
            cmd.extend(["--login", args.login])
        cmd.extend(
            [
                "--script",
                str(script_path),
                "--",
                args.job_name_prefix,
                args.log_dir,
                args.partition,
                str(args.ntasks),
                str(args.cpus_per_task),
                args.time,
                args.mem_per_cpu,
                args.mail_type,
                "1" if args.dry_run else "0",
                *args.cmd,
            ]
        )
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.stdout and not args.dry_run:
            _register_jobs(result.stdout, args.job_name_prefix, script_path)
        return result.returncode
    finally:
        script_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Queue a chain of HPC commands as dependent Slurm jobs (afterok).",
    )
    parser.add_argument("--login", default=None, help="Remote login in user@host form.")
    parser.add_argument("--job-name-prefix", default="hpcq", help="Prefix for submitted job names.")
    parser.add_argument("--log-dir", default="/data/EECS-LITQ/fran_storage/logs", help="Slurm log directory.")
    parser.add_argument("--partition", default="compute", help="Slurm partition.")
    parser.add_argument("--ntasks", type=int, default=1, help="Slurm -n value per queued job.")
    parser.add_argument("--cpus-per-task", type=int, default=16, help="Slurm --cpus-per-task value per queued job.")
    parser.add_argument("--time", default="3:00:00", help="Slurm time limit per job.")
    parser.add_argument("--mem-per-cpu", default="8G", help="Slurm memory per CPU.")
    parser.add_argument("--mail-type", default="NONE", help="Slurm --mail-type value, or NONE.")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved sbatch commands without submitting.")
    parser.add_argument(
        "--cmd",
        action="append",
        default=[],
        help="Command to queue; repeat --cmd for each step in order.",
    )
    args = parser.parse_known_args()[0]
    if not args.cmd:
        raise SystemExit("At least one --cmd is required.")
    raise SystemExit(main(args))
