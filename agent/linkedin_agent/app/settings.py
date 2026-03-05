from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    db_path: Path
    feeds_config: Path
    sources_experiments: Path
    sources_notes: Path
    sources_feeds: Path
    drafts_dir: Path
    scheduler_interval_seconds: int = 300
    min_relevance_score: float = 1.2
    auto_post_enabled: bool = False
    x_enabled: bool = False


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower().strip() in {"1", "true", "yes", "on"}


def load_settings(base_dir: Path | None = None) -> Settings:
    root = (base_dir or Path(__file__).resolve().parents[1]).resolve()
    return Settings(
        base_dir=root,
        db_path=root / "app.db",
        feeds_config=root / "config" / "feeds.yaml",
        sources_experiments=root / "sources" / "experiments",
        sources_notes=root / "sources" / "notes",
        sources_feeds=root / "sources" / "feeds",
        drafts_dir=root / "drafts",
        scheduler_interval_seconds=int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "300")),
        min_relevance_score=float(os.getenv("MIN_RELEVANCE_SCORE", "1.2")),
        auto_post_enabled=_bool_env("AUTO_POST_ENABLED", False),
        x_enabled=_bool_env("X_ENABLED", False),
    )
