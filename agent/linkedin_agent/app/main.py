from __future__ import annotations

import json
from contextlib import asynccontextmanager
from html import escape

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from publishers.linkedin import publish_or_export
from publishers.x_publisher import publish_x

from .audit import log_event
from .db import connect, fetch_all, init_db
from .repository import get_draft, list_drafts, mark_published, set_status, update_draft
from .scheduler import build_scheduler
from .settings import load_settings
from .workflow import run_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    init_db(settings.db_path)
    settings.sources_experiments.mkdir(parents=True, exist_ok=True)
    settings.sources_notes.mkdir(parents=True, exist_ok=True)
    settings.sources_feeds.mkdir(parents=True, exist_ok=True)
    settings.drafts_dir.mkdir(parents=True, exist_ok=True)

    app.state.settings = settings
    app.state.scheduler = build_scheduler({"settings": settings})
    app.state.scheduler.start()
    try:
        yield
    finally:
        app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="DocSmart LinkedIn Agent", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/run-once")
def api_run_once() -> dict:
    s = app.state.settings
    return run_pipeline(
        db_path=s.db_path,
        experiments_dir=s.sources_experiments,
        notes_dir=s.sources_notes,
        feeds_config=s.feeds_config,
        feed_cache_dir=s.sources_feeds,
        min_score=s.min_relevance_score,
    )


@app.get("/api/drafts")
def api_list_drafts(status: str | None = Query(default=None)) -> list[dict]:
    return list_drafts(app.state.settings.db_path, status)


@app.get("/api/drafts/{draft_id}")
def api_get_draft(draft_id: int) -> dict:
    draft = get_draft(app.state.settings.db_path, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="draft not found")
    return draft


@app.post("/api/drafts/{draft_id}/approve")
def api_approve_draft(draft_id: int, reviewer_notes: str = "") -> dict[str, str]:
    ok = set_status(app.state.settings.db_path, draft_id, "approved", reviewer_notes)
    if not ok:
        raise HTTPException(status_code=404, detail="draft not found")
    return {"status": "approved"}


@app.post("/api/drafts/{draft_id}/reject")
def api_reject_draft(draft_id: int, reviewer_notes: str = "") -> dict[str, str]:
    ok = set_status(app.state.settings.db_path, draft_id, "rejected", reviewer_notes)
    if not ok:
        raise HTTPException(status_code=404, detail="draft not found")
    return {"status": "rejected"}


@app.post("/api/drafts/{draft_id}/publish")
def api_publish_draft(draft_id: int, platform: str = Query("linkedin", pattern="^(linkedin|x)$")) -> dict:
    s = app.state.settings
    draft = get_draft(s.db_path, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="draft not found")
    if draft["status"] != "approved":
        raise HTTPException(status_code=400, detail="draft must be approved before publish")

    if platform == "linkedin":
        result = publish_or_export(draft, drafts_dir=s.drafts_dir, dry_run=not s.auto_post_enabled)
    else:
        result = publish_x(draft, enabled=s.x_enabled)

    log_event(s.db_path, "publish_attempt", "draft", str(draft_id), {"platform": platform, "result": result})
    if result.get("status") == "posted" or result.get("mode") == "api":
        mark_published(s.db_path, draft_id, platform=platform, result=result)
    return result


@app.get("/api/audit")
def api_audit(limit: int = 100) -> list[dict]:
    with connect(app.state.settings.db_path) as conn:
        rows = fetch_all(conn, "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    for row in rows:
        row["payload"] = json.loads(row["payload_json"])
    return rows


@app.post("/api/drafts/{draft_id}/update")
def api_update_draft(
    draft_id: int,
    audience_tag: str,
    claim_level: str,
    source_refs_json: str,
    linkedin_short: str,
    linkedin_long: str,
    x_version: str,
    reviewer_notes: str = "",
) -> dict[str, str]:
    try:
        refs = json.loads(source_refs_json)
        if not isinstance(refs, list):
            raise ValueError
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="source_refs_json must be a JSON list") from exc

    ok = update_draft(
        db_path=app.state.settings.db_path,
        draft_id=draft_id,
        audience_tag=audience_tag,
        claim_level=claim_level,
        source_refs=refs,
        linkedin_short=linkedin_short,
        linkedin_long=linkedin_long,
        x_version=x_version,
        reviewer_notes=reviewer_notes,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="draft not found")
    return {"status": "updated"}


@app.get("/ui/drafts", response_class=HTMLResponse)
def ui_drafts() -> str:
    drafts = list_drafts(app.state.settings.db_path)
    rows = "".join(
        (
            "<tr>"
            f"<td>{d['id']}</td><td>{escape(d['status'])}</td><td>{escape(d['audience_tag'])}</td>"
            f"<td>{escape(d['claim_level'])}</td><td><a href='/ui/drafts/{d['id']}'>open</a></td>"
            "</tr>"
        )
        for d in drafts
    )
    return (
        "<html><body><h1>Approval Queue</h1>"
        "<p>No auto-posting by default. Approve first, then publish.</p>"
        "<table border='1' cellpadding='6'><tr><th>ID</th><th>Status</th><th>Audience</th><th>Claim</th><th>View</th></tr>"
        f"{rows}</table></body></html>"
    )


@app.get("/ui/drafts/{draft_id}", response_class=HTMLResponse)
def ui_draft_detail(draft_id: int) -> str:
    d = get_draft(app.state.settings.db_path, draft_id)
    if not d:
        raise HTTPException(status_code=404, detail="draft not found")
    refs_json = json.dumps(d["source_refs"])
    return f"""
<html><body>
<h1>Draft {d['id']}</h1>
<p>Status: <b>{escape(d['status'])}</b></p>
<form method='post' action='/ui/drafts/{d['id']}/save'>
  <label>Audience tag</label><br><input name='audience_tag' value='{escape(d['audience_tag'])}' size='60'/><br>
  <label>Claim level</label><br>
  <select name='claim_level'>
    <option {'selected' if d['claim_level']=='idea' else ''}>idea</option>
    <option {'selected' if d['claim_level']=='prototype' else ''}>prototype</option>
    <option {'selected' if d['claim_level']=='validated' else ''}>validated</option>
    <option {'selected' if d['claim_level']=='published' else ''}>published</option>
  </select><br>
  <label>Source refs JSON</label><br><textarea name='source_refs_json' rows='3' cols='90'>{escape(refs_json)}</textarea><br>
  <label>LinkedIn short</label><br><textarea name='linkedin_short' rows='6' cols='90'>{escape(d['linkedin_short'])}</textarea><br>
  <label>LinkedIn long</label><br><textarea name='linkedin_long' rows='14' cols='90'>{escape(d['linkedin_long'])}</textarea><br>
  <label>X version</label><br><textarea name='x_version' rows='4' cols='90'>{escape(d['x_version'])}</textarea><br>
  <label>Reviewer notes</label><br><textarea name='reviewer_notes' rows='3' cols='90'>{escape(d.get('reviewer_notes') or '')}</textarea><br><br>
  <button type='submit'>Save</button>
</form>
<form method='post' action='/ui/drafts/{d['id']}/approve'><button type='submit'>Approve</button></form>
<form method='post' action='/ui/drafts/{d['id']}/reject'><button type='submit'>Reject</button></form>
<form method='post' action='/ui/drafts/{d['id']}/publish'><button type='submit'>Publish LinkedIn</button></form>
<p><a href='/ui/drafts'>Back</a></p>
</body></html>
"""


@app.post("/ui/drafts/{draft_id}/save", response_class=HTMLResponse)
async def ui_save_draft(draft_id: int, request: Request) -> HTMLResponse:
    from urllib.parse import parse_qs

    raw = (await request.body()).decode("utf-8", errors="ignore")
    form = {k: v[-1] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    api_update_draft(
        draft_id=draft_id,
        audience_tag=form.get("audience_tag", ""),
        claim_level=form.get("claim_level", "idea"),
        source_refs_json=form.get("source_refs_json", "[]"),
        linkedin_short=form.get("linkedin_short", ""),
        linkedin_long=form.get("linkedin_long", ""),
        x_version=form.get("x_version", ""),
        reviewer_notes=form.get("reviewer_notes", ""),
    )
    return HTMLResponse(f"<html><body>Saved. <a href='/ui/drafts/{draft_id}'>Back</a></body></html>")


@app.post("/ui/drafts/{draft_id}/approve", response_class=HTMLResponse)
def ui_approve_draft(draft_id: int) -> HTMLResponse:
    api_approve_draft(draft_id)
    return HTMLResponse(f"<html><body>Approved. <a href='/ui/drafts/{draft_id}'>Back</a></body></html>")


@app.post("/ui/drafts/{draft_id}/reject", response_class=HTMLResponse)
def ui_reject_draft(draft_id: int) -> HTMLResponse:
    api_reject_draft(draft_id)
    return HTMLResponse(f"<html><body>Rejected. <a href='/ui/drafts/{draft_id}'>Back</a></body></html>")


@app.post("/ui/drafts/{draft_id}/publish", response_class=HTMLResponse)
def ui_publish_draft(draft_id: int) -> HTMLResponse:
    result = api_publish_draft(draft_id, platform="linkedin")
    return HTMLResponse(
        f"<html><body>Publish result: <pre>{escape(json.dumps(result, indent=2))}</pre><a href='/ui/drafts/{draft_id}'>Back</a></body></html>"
    )
