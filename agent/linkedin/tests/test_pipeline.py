from __future__ import annotations

import json
from pathlib import Path

from app.db import connect, fetch_one, init_db
from app.generation import generate_from_sources
from app.ingestion import ingest_all
from app.repository import create_draft, set_status
from app.settings import Settings
from app.workflow import run_pipeline
from publishers.linkedin import publish_or_export


def build_test_tree(tmp_path: Path) -> Settings:
    root = tmp_path / "linkedin_agent"
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "experiments").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "notes").mkdir(parents=True, exist_ok=True)
    (root / "sources" / "feeds").mkdir(parents=True, exist_ok=True)
    (root / "drafts").mkdir(parents=True, exist_ok=True)

    (root / "config" / "feeds.yaml").write_text("feeds: []\n", encoding="utf-8")
    (root / "sources" / "experiments" / "exp.json").write_text(
        json.dumps(
            {
                "title": "Validated radiology workflow",
                "summary": "Validated pilot in NHS reporting pathway improved turnaround and safety controls.",
                "images": ["plot.png"],
            }
        ),
        encoding="utf-8",
    )
    (root / "sources" / "notes" / "note.md").write_text(
        "# Clinical AI governance\n\nRegulatory awareness and validation evidence are mandatory.",
        encoding="utf-8",
    )

    return Settings(
        base_dir=root,
        db_path=root / "app.db",
        feeds_config=root / "config" / "feeds.yaml",
        sources_experiments=root / "sources" / "experiments",
        sources_notes=root / "sources" / "notes",
        sources_feeds=root / "sources" / "feeds",
        drafts_dir=root / "drafts",
        scheduler_interval_seconds=300,
        min_relevance_score=0.2,
        auto_post_enabled=False,
        x_enabled=False,
    )


def test_ingest_and_generate(tmp_path: Path) -> None:
    s = build_test_tree(tmp_path)
    init_db(s.db_path)

    result = run_pipeline(
        db_path=s.db_path,
        experiments_dir=s.sources_experiments,
        notes_dir=s.sources_notes,
        feeds_config=s.feeds_config,
        feed_cache_dir=s.sources_feeds,
        min_score=s.min_relevance_score,
    )

    assert result["ingestion"]["inserted"] >= 2
    assert result["generation"]["created"] >= 1

    with connect(s.db_path) as conn:
        row = fetch_one(conn, "SELECT * FROM drafts ORDER BY id DESC LIMIT 1")
    assert row is not None
    assert row["audience_tag"]
    assert row["claim_level"] in {"idea", "prototype", "validated", "published"}
    assert row["source_refs_json"]


def test_metadata_enforced(tmp_path: Path) -> None:
    s = build_test_tree(tmp_path)
    init_db(s.db_path)

    try:
        create_draft(
            db_path=s.db_path,
            audience_tag="",
            claim_level="idea",
            source_refs=["a"],
            linkedin_short="x",
            linkedin_long="y",
            x_version="z",
        )
        assert False, "Expected ValueError for missing audience_tag"
    except ValueError:
        pass


def test_approval_required_for_publish_export(tmp_path: Path) -> None:
    s = build_test_tree(tmp_path)
    init_db(s.db_path)
    ingest_all(s.db_path, s.sources_experiments, s.sources_notes, s.feeds_config, s.sources_feeds)
    generate_from_sources(s.db_path, min_score=0.2)

    with connect(s.db_path) as conn:
        draft = fetch_one(conn, "SELECT * FROM drafts ORDER BY id DESC LIMIT 1")
    assert draft is not None

    parsed = {
        "id": draft["id"],
        "audience_tag": draft["audience_tag"],
        "claim_level": draft["claim_level"],
        "source_refs": json.loads(draft["source_refs_json"]),
        "linkedin_long": draft["linkedin_long"],
    }

    set_status(s.db_path, int(draft["id"]), "approved")
    result = publish_or_export(parsed, drafts_dir=s.drafts_dir, dry_run=True)
    assert result["mode"] == "export"
    assert (s.drafts_dir / "exports" / f"linkedin_draft_{draft['id']}.txt").exists()
