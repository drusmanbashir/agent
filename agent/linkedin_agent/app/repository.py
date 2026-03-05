from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .audit import log_event
from .compliance import assert_required_metadata
from .db import connect, fetch_all, fetch_one, utc_now


def create_draft(
    db_path: Path,
    audience_tag: str,
    claim_level: str,
    source_refs: list[str],
    linkedin_short: str,
    linkedin_long: str,
    x_version: str,
) -> int:
    assert_required_metadata(audience_tag, claim_level, source_refs)
    now = utc_now()
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO drafts (
              audience_tag, claim_level, source_refs_json,
              linkedin_short, linkedin_long, x_version,
              status, reviewer_notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', '', ?, ?)
            """,
            (
                audience_tag,
                claim_level,
                json.dumps(source_refs),
                linkedin_short,
                linkedin_long,
                x_version,
                now,
                now,
            ),
        )
        draft_id = int(cur.lastrowid)
    log_event(db_path, "generated", "draft", str(draft_id), {"claim_level": claim_level, "audience_tag": audience_tag})
    return draft_id


def list_drafts(db_path: Path, status: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        if status:
            rows = fetch_all(conn, "SELECT * FROM drafts WHERE status = ? ORDER BY id DESC", (status,))
        else:
            rows = fetch_all(conn, "SELECT * FROM drafts ORDER BY id DESC")
    for row in rows:
        row["source_refs"] = json.loads(row["source_refs_json"])
    return rows


def get_draft(db_path: Path, draft_id: int) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = fetch_one(conn, "SELECT * FROM drafts WHERE id = ?", (draft_id,))
    if not row:
        return None
    row["source_refs"] = json.loads(row["source_refs_json"])
    return row


def update_draft(
    db_path: Path,
    draft_id: int,
    audience_tag: str,
    claim_level: str,
    source_refs: list[str],
    linkedin_short: str,
    linkedin_long: str,
    x_version: str,
    reviewer_notes: str,
) -> bool:
    assert_required_metadata(audience_tag, claim_level, source_refs)
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE drafts
            SET audience_tag = ?, claim_level = ?, source_refs_json = ?,
                linkedin_short = ?, linkedin_long = ?, x_version = ?,
                reviewer_notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                audience_tag,
                claim_level,
                json.dumps(source_refs),
                linkedin_short,
                linkedin_long,
                x_version,
                reviewer_notes,
                utc_now(),
                draft_id,
            ),
        )
    ok = cur.rowcount > 0
    if ok:
        log_event(db_path, "edited", "draft", str(draft_id), {"claim_level": claim_level})
    return ok


def set_status(db_path: Path, draft_id: int, status: str, reviewer_notes: str = "") -> bool:
    with connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE drafts SET status = ?, reviewer_notes = ?, updated_at = ? WHERE id = ?",
            (status, reviewer_notes, utc_now(), draft_id),
        )
    ok = cur.rowcount > 0
    if ok:
        event = "approved" if status == "approved" else "rejected" if status == "rejected" else "status_changed"
        log_event(db_path, event, "draft", str(draft_id), {"status": status, "reviewer_notes": reviewer_notes})
    return ok


def mark_published(db_path: Path, draft_id: int, platform: str, result: dict[str, Any]) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE drafts SET status = 'published', updated_at = ? WHERE id = ?", (utc_now(), draft_id))
    log_event(db_path, "publish_attempt", "draft", str(draft_id), {"platform": platform, "result": result})
