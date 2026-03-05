from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

import app.main as main
from app.db import init_db
from app.settings import Settings
from app.workflow import run_pipeline


def test_publish_requires_approval_without_testclient(tmp_path: Path) -> None:
    root = tmp_path / "linkedin_agent"
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "experiments").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "notes").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "feeds").mkdir(parents=True, exist_ok=True)
    (root / "drafts").mkdir(parents=True, exist_ok=True)

    (root / "config" / "feeds.yaml").write_text("feeds: []\n", encoding="utf-8")
    (root / "sources" / "experiments" / "exp.json").write_text(
        json.dumps({"title": "Prototype governance note", "summary": "NHS pilot for radiology AI workflow."}),
        encoding="utf-8",
    )

    s = Settings(
        base_dir=root,
        db_path=root / "app.db",
        feeds_config=root / "config" / "feeds.yaml",
        sources_experiments=root / "sources" / "experiments",
        sources_notes=root / "sources" / "notes",
        sources_feeds=root / "sources" / "feeds",
        drafts_dir=root / "drafts",
        min_relevance_score=0.1,
        auto_post_enabled=False,
        x_enabled=False,
    )

    init_db(s.db_path)
    run_pipeline(
        db_path=s.db_path,
        experiments_dir=s.sources_experiments,
        notes_dir=s.sources_notes,
        feeds_config=s.feeds_config,
        feed_cache_dir=s.sources_feeds,
        min_score=s.min_relevance_score,
    )

    main.app.state.settings = s

    drafts = main.api_list_drafts(status=None)
    assert drafts
    draft_id = drafts[0]["id"]

    try:
        main.api_publish_draft(draft_id, "linkedin")
        assert False, "Expected approval gate to block publish"
    except HTTPException as exc:
        assert exc.status_code == 400

    main.api_approve_draft(draft_id)
    result = main.api_publish_draft(draft_id, "linkedin")
    assert result["mode"] == "export"
