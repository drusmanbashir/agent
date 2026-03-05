from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from .workflow import run_pipeline


def build_scheduler(state: dict) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    settings = state["settings"]

    def job() -> None:
        run_pipeline(
            db_path=settings.db_path,
            experiments_dir=settings.sources_experiments,
            notes_dir=settings.sources_notes,
            feeds_config=settings.feeds_config,
            feed_cache_dir=settings.sources_feeds,
            min_score=settings.min_relevance_score,
        )

    scheduler.add_job(job, "interval", seconds=settings.scheduler_interval_seconds, id="pipeline")
    return scheduler
