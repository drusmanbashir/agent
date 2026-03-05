from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def log_event_via(
    db_path: Path,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    connect_fn: Callable,
    utc_now_fn: Callable[[], str],
) -> None:
    with connect_fn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (event_type, entity_type, entity_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, entity_type, entity_id, json.dumps(payload), utc_now_fn()),
        )
