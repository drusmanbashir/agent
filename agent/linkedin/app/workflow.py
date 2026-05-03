from __future__ import annotations

from pathlib import Path

from .generation import generate_from_sources
from .ingestion import ingest_all


def run_pipeline(db_path: Path, experiments_dir: Path, notes_dir: Path, feeds_config: Path, feed_cache_dir: Path, min_score: float) -> dict[str, dict[str, int]]:
    ingestion = ingest_all(
        db_path=db_path,
        experiments_dir=experiments_dir,
        notes_dir=notes_dir,
        feeds_config=feeds_config,
        feed_cache_dir=feed_cache_dir,
    )
    generation = generate_from_sources(db_path=db_path, min_score=min_score)
    return {"ingestion": ingestion, "generation": generation}
