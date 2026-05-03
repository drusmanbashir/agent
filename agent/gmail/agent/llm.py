from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class LLMResult:
    data: Dict[str, Any]


def classify_email_metadata_stub(subject: str, sender: str) -> LLMResult:
    # Placeholder. Keep deterministic until you wire OpenAI/Claude.
    subj = (subject or "").lower()
    if "review" in subj or "reviewer" in subj:
        return LLMResult({"likely_activity": "peer_review", "confidence": 0.7})
    if "accepted" in subj or "proof" in subj or "published" in subj:
        return LLMResult({"likely_activity": "publication", "confidence": 0.7})
    if "certificate" in subj or "cpd" in subj or "attendance" in subj:
        return LLMResult({"likely_activity": "cpd_course", "confidence": 0.7})
    return LLMResult({"likely_activity": "ignore", "confidence": 0.2})
