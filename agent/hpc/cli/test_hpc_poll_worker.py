from __future__ import annotations

import os
import signal
import subprocess
import textwrap
from pathlib import Path


SCRIPT = Path(__file__).with_name("hpc_poll_worker.sh")


def write_file(path: Path, contents: str, mode: int = 0o644) -> Path:
    path.write_text(contents, encoding="utf-8")
    path.chmod(mode)
    return path


def test_spawn_writes_baseline_meta_before_child_updates(tmp_path: Path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    write_file(job_dir / "job.meta", "poll_schedule=1\n")
    bash_env = write_file(
        tmp_path / "delay-run.sh",
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"run\" ]]; then\n"
        "  sleep 5\n"
        "fi\n",
        0o755,
    )
    env = dict(os.environ)
    env["BASH_ENV"] = str(bash_env)
    env["HPC_SSHPASS_BIN"] = "__missing_sshpass__"

    result = subprocess.run(
        [str(SCRIPT), "spawn", "--job-id", "12345", "--job-dir", str(job_dir)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    worker_pid = int((job_dir / "worker.pid").read_text(encoding="utf-8").strip())
    try:
        meta = (job_dir / "worker.meta").read_text(encoding="utf-8")
        assert "poll_worker_status=spawned" in result.stdout
        assert "worker_state=spawned" in meta
        assert f"worker_pid={worker_pid}" in meta
    finally:
        os.kill(worker_pid, signal.SIGTERM)


def test_run_worker_overwrites_meta_with_finished_state(tmp_path: Path) -> None:
    job_dir = tmp_path / "job"
    remote_dir = tmp_path / "remote"
    job_dir.mkdir()
    remote_dir.mkdir()

    write_file(remote_dir / "slurm-12345.out", "stdout\n")
    write_file(remote_dir / "slurm-12345.err", "stderr\n")
    write_file(
        job_dir / "job.meta",
        (
            "job_name=train-kits23\n"
            "poll_schedule=0\n"
            f"log_out_template={remote_dir}/slurm-%j.out\n"
            f"log_err_template={remote_dir}/slurm-%j.err\n"
        ),
    )

    ssh_script = write_file(
        tmp_path / "ssh.sh",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            calls="{tmp_path}/ssh.calls"
            count=0
            if [[ -f "${{calls}}" ]]; then
              count="$(cat "${{calls}}")"
            fi
            count="$((count + 1))"
            printf '%s\n' "${{count}}" > "${{calls}}"
            if [[ "${{count}}" == "1" ]]; then
              exit 0
            fi
            if [[ "${{count}}" == "2" ]]; then
              printf '12345|COMPLETED|0:0|12\n'
              exit 0
            fi
            exit 1
            """
        ),
        0o755,
    )
    rsync_script = write_file(
        tmp_path / "rsync.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            src="$2"
            dest="$3"
            cp "${src#*:}" "${dest}"
            """
        ),
        0o755,
    )
    registry_script = write_file(
        tmp_path / "registry.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
        0o755,
    )

    env = dict(os.environ)
    env["HPC_SSH_SCRIPT"] = str(ssh_script)
    env["HPC_RSYNC_SCRIPT"] = str(rsync_script)
    env["HPC_JOB_REGISTRY_SCRIPT"] = str(registry_script)
    env["HPC_LOGIN"] = "fake-login"

    result = subprocess.run(
        [str(SCRIPT), "run", "--job-id", "12345", "--job-dir", str(job_dir)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    meta = (job_dir / "worker.meta").read_text(encoding="utf-8")
    done = (job_dir / "worker.done").read_text(encoding="utf-8")

    assert "poll_worker_status=finished job_id=12345 state=COMPLETED exit=0:0" in result.stdout
    assert "worker_state=finished" in meta
    assert "final_state=COMPLETED" in meta
    assert "final_state=COMPLETED" in done
    assert (job_dir / "slurm-12345.out").read_text(encoding="utf-8") == "stdout\n"
    assert (job_dir / "slurm-12345.err").read_text(encoding="utf-8") == "stderr\n"
