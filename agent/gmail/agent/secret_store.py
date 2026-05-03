from __future__ import annotations

import os
from pathlib import Path


DEFAULT_SECRETS_FILE = Path("/s/agent_rw/conf/agent_repo/secrets.env")


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load_shared_secrets(path: Path | None = None) -> dict[str, str]:
    target = path or Path(os.getenv("AGENT_SECRETS_FILE", str(DEFAULT_SECRETS_FILE)))
    if not target.exists():
        return {}
    loaded = _parse_env_file(target)
    for key, value in loaded.items():
        os.environ.setdefault(key, value)
    return loaded
