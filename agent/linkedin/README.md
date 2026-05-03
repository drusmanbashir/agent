# LinkedIn Agent (DocSmart)

Compliant social-content agent for DocSmart with approval-gated publishing.

## Compliance constraints implemented
- No scraping or browser automation for LinkedIn.
- No storing or processing patient-identifiable data (basic sanitizer + reject patterns).
- Every draft stores and displays: `audience_tag`, `claim_level` (`idea|prototype|validated|published`), `source_refs`.
- No auto-posting by default (`auto_post_enabled: false`).

## Features
- FastAPI app + SQLite persistence.
- Scheduler for ingestion/generation loop.
- Ingestion from:
  - `sources/experiments` (`*.json` + optional PNG references)
  - `sources/notes` (`*.md`)
  - RSS feeds configured in `config/feeds.yaml`
- Filtering with keyword and semantic scoring against a DocSmart relevance profile.
- Draft generation:
  - LinkedIn short
  - LinkedIn long
  - X draft derived from LinkedIn short
- Approval UI:
  - list drafts
  - view/edit draft
  - approve/reject draft
- Publishing:
  - LinkedIn Posts API publisher if credentials/scopes are present
  - else export copy/paste packs to `drafts/exports/`
  - X publisher module behind config flag
- Audit logging for all ingestion, generation, approvals, and publish attempts.

## Project layout
- `app/` core application code
- `publishers/` LinkedIn and X publishing modules
- `sources/experiments`, `sources/notes`, `sources/feeds` input sources
- `drafts/` local export artifacts
- `config/feeds.yaml` RSS feed config

## Run locally
```bash
cd agent/linkedin
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
uvicorn app.main:app --reload --port 8080
```

Open:
- UI: `http://127.0.0.1:8080/ui/drafts`
- API docs: `http://127.0.0.1:8080/docs`

## Dry-run mode
Default is dry-run style:
- `auto_post_enabled=false`
- publishing endpoint only publishes approved drafts
- LinkedIn without creds exports copy/paste packs instead of posting
- X posting disabled unless explicitly enabled

Environment vars for optional publishing:
- `LINKEDIN_ACCESS_TOKEN`
- `LINKEDIN_AUTHOR_URN` (example: `urn:li:person:...`)
- `LINKEDIN_SCOPES` (must include `w_member_social`)
- `X_BEARER_TOKEN` (used only when `x_enabled=true`)
- `LINKEDIN_DB_PATH` (optional; defaults to `/s/agent_rw/state/agent_repo/linkedin/app.db`)

These can be sourced from the shared secrets file:
- `/s/agent_rw/conf/agent_repo/secrets.env`

## Minimal workflow
1. Add sample content under `sources/experiments` and `sources/notes`.
2. Set feeds in `config/feeds.yaml`.
3. Trigger ingestion/generation:
   - `POST /api/run-once`
4. Review and edit drafts in UI.
5. Approve drafts.
6. Publish via `POST /api/drafts/{id}/publish` (or export pack fallback).

## Tests
```bash
pytest -q
```
