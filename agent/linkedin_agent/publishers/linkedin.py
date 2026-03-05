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


def _credentials_available() -> tuple[bool, str]:
    _load_shared_secrets_env()
    token = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    author = os.getenv("LINKEDIN_AUTHOR_URN", "")
    scopes = set(s.strip() for s in os.getenv("LINKEDIN_SCOPES", "").split(",") if s.strip())
    if not token or not author:
        return False, "missing token or author urn"
    if "w_member_social" not in scopes:
        return False, "missing w_member_social scope"
    return True, "ok"


def publish_or_export(draft: dict[str, Any], drafts_dir: Path, dry_run: bool = True) -> dict[str, Any]:
    drafts_dir.mkdir(parents=True, exist_ok=True)
    allowed, reason = _credentials_available()
    if dry_run or not allowed:
        export_dir = drafts_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        out = export_dir / f"linkedin_draft_{draft['id']}.txt"
        out.write_text(
            f"Audience: {draft['audience_tag']}\n"
            f"Claim level: {draft['claim_level']}\n"
            f"Sources: {', '.join(draft['source_refs'])}\n\n"
            f"{draft['linkedin_long']}\n",
            encoding="utf-8",
        )
        return {"mode": "export", "file": str(out), "reason": "dry_run" if dry_run else reason}

    payload = {
        "author": os.environ["LINKEDIN_AUTHOR_URN"],
        "commentary": draft["linkedin_long"],
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    req = urllib.request.Request(
        url="https://api.linkedin.com/rest/posts",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}",
            "LinkedIn-Version": "202411",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
            body = resp.read().decode("utf-8", errors="ignore")
        return {"mode": "api", "status": "posted", "response": body}
    except urllib.error.HTTPError as exc:
        return {"mode": "api", "status": "error", "code": exc.code, "detail": exc.read().decode("utf-8", errors="ignore")}
