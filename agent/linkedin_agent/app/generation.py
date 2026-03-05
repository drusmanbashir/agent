from __future__ import annotations

from pathlib import Path

from .db import connect, fetch_all
from .models import SourceItem
from .filtering import score_item
from .repository import create_draft


def _detect_claim_level(text: str) -> str:
    low = text.lower()
    if any(token in low for token in ["peer-reviewed", "published", "journal"]):
        return "published"
    if any(token in low for token in ["validated", "prospective", "audit results"]):
        return "validated"
    if any(token in low for token in ["pilot", "prototype", "mvp"]):
        return "prototype"
    return "idea"


def _build_linkedin_short(title: str, summary: str, pillar: str, claim_level: str) -> str:
    return (
        f"[{pillar}] {title}\n\n"
        f"Claim level: {claim_level}.\n"
        f"Key signal: {summary[:220].strip()}\n\n"
        "DocSmart focus: clinically credible AI with measurable workflow impact in NHS pathways."
    )


def _build_linkedin_long(title: str, body: str, pillar: str, claim_level: str, refs: list[str]) -> str:
    refs_joined = "\n".join(f"- {r}" for r in refs)
    return (
        f"Audience: NHS clinical and operational leaders\n"
        f"Pillar: {pillar}\n"
        f"Claim level: {claim_level}\n\n"
        f"{title}\n\n"
        f"{body[:1200]}\n\n"
        "What this means for deployment:\n"
        "- clinical safety and governance come first\n"
        "- technical reliability must be measurable\n"
        "- implementation speed only matters with outcomes\n\n"
        f"Sources:\n{refs_joined}"
    )


def _build_x_from_linkedin(linkedin_short: str) -> str:
    trimmed = linkedin_short.replace("\n", " ")
    return (trimmed[:250] + "...") if len(trimmed) > 253 else trimmed


def generate_from_sources(db_path: Path, min_score: float = 1.2) -> dict[str, int]:
    with connect(db_path) as conn:
        sources = fetch_all(
            conn,
            "SELECT source_id, title, content, source_ref, source_type FROM ingestions ORDER BY id DESC LIMIT 50",
        )

    created = 0
    evaluated = 0
    for src in sources:
        evaluated += 1
        scored = score_item(SourceItem(
            source_type=src["source_type"],
            source_id=src["source_id"],
            title=src["title"],
            content=src["content"],
            source_ref=src["source_ref"],
        ))
        if scored.total_score < min_score:
            continue

        claim_level = _detect_claim_level(src["content"])
        pillar = "technical depth" if scored.semantic_score >= 0.15 else "clinical credibility"
        audience_tag = "nhs-clinical-leaders"
        refs = [src["source_ref"]]

        linkedin_short = _build_linkedin_short(src["title"], src["content"], pillar, claim_level)
        linkedin_long = _build_linkedin_long(src["title"], src["content"], pillar, claim_level, refs)
        x_version = _build_x_from_linkedin(linkedin_short)

        create_draft(
            db_path=db_path,
            audience_tag=audience_tag,
            claim_level=claim_level,
            source_refs=refs,
            linkedin_short=linkedin_short,
            linkedin_long=linkedin_long,
            x_version=x_version,
        )
        created += 1

    return {"evaluated": evaluated, "created": created}
