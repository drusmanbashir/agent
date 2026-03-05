from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ClaimLevel = Literal["idea", "prototype", "validated", "published"]
DraftStatus = Literal["pending", "approved", "rejected", "published"]


@dataclass
class SourceItem:
    source_type: str
    source_id: str
    title: str
    content: str
    source_ref: str


@dataclass
class ScoredItem:
    item: SourceItem
    keyword_score: float
    semantic_score: float
    total_score: float


@dataclass
class DraftPayload:
    audience_tag: str
    claim_level: ClaimLevel
    source_refs: list[str]
    linkedin_short: str
    linkedin_long: str
    x_version: str
    status: DraftStatus = "pending"
    created_at: datetime | None = None
