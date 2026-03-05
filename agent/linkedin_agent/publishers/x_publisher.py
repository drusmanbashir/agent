from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_SHARED_LOADED = False


def _load_shared_secrets_env() -> None:
    global _SHARED_LOADED
    if _SHARED_LOADED:
        return
    _SHARED_LOADED = True
    path = Path(os.getenv("AGENT_SECRETS_FILE", "/s/agent_rw/conf/agent_repo/secrets.env"))
    if not path.exists():
        return
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
        if key and key not in os.environ:
            os.environ[key] = value


def publish_x(draft: dict[str, Any], enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {"status": "disabled", "reason": "x_enabled=false"}

    _load_shared_secrets_env()
    token = os.getenv("X_BEARER_TOKEN", "")
    if not token:
        return {"status": "disabled", "reason": "missing X_BEARER_TOKEN"}

    payload = {"text": draft["x_version"]}
    req = urllib.request.Request(
        url="https://api.x.com/2/tweets",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
            body = resp.read().decode("utf-8", errors="ignore")
        return {"status": "posted", "response": body}
    except urllib.error.HTTPError as exc:
        return {"status": "error", "code": exc.code, "detail": exc.read().decode("utf-8", errors="ignore")}
