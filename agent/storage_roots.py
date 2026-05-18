from __future__ import annotations

import json
from functools import cache
from pathlib import Path

STORAGE_ROOTS_PATH = Path("/s/agent_rw/conf/agent_repo/storage_roots.json")


@cache
def storage_roots() -> dict[str, Path]:
    payload = json.loads(STORAGE_ROOTS_PATH.read_text(encoding="utf-8"))
    return {name: Path(value).expanduser() for name, value in payload.items()}


def storage_root(name: str) -> Path:
    return storage_roots()[name]
