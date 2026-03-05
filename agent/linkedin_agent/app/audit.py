from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .db import connect, utc_now

try:
    from ds_shared.audit import log_event_via  # type: ignore
except ModuleNotFoundError:
    shared_dir = Path(__file__).resolve().parents[2] / "shared"
    if str(shared_dir) not in sys.path:
        sys.path.insert(0, str(shared_dir))
    from ds_shared.audit import log_event_via  # type: ignore


def log_event(db_path: Path, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
    log_event_via(
        db_path=db_path,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        connect_fn=connect,
        utc_now_fn=utc_now,
    )
