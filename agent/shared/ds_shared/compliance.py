from __future__ import annotations

import re
from typing import Optional

PII_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\bNHS\s*No\.?\s*[:#]?\s*\d{6,12}\b", re.IGNORECASE),
    re.compile(r"\bDOB\b\s*[:#]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", re.IGNORECASE),
    re.compile(r"\b\d{3}\s?\d{3}\s?\d{4}\b"),
    re.compile(r"\b(MRN|HOSP|HOSPITAL)\s*[:#]?\s*\w{4,}\b", re.IGNORECASE),
]

REQUIRED_CLAIM_LEVELS = {"idea", "prototype", "validated", "published"}


def contains_pii(text: str) -> bool:
    trimmed = (text or "")[:2000]
    return any(p.search(trimmed) for p in PII_PATTERNS)


def assert_no_pii(text: str) -> None:
    if contains_pii(text):
        raise ValueError("Potential patient-identifiable data detected")


def detect_pii_signal(text: str) -> Optional[str]:
    trimmed = (text or "")[:2000]
    for idx, pattern in enumerate(PII_PATTERNS, start=1):
        if pattern.search(trimmed):
            return f"pii_pattern_{idx}"
    return None


def assert_required_metadata(audience_tag: str, claim_level: str, source_refs: list[str]) -> None:
    if not audience_tag.strip():
        raise ValueError("audience_tag is required")
    if claim_level not in REQUIRED_CLAIM_LEVELS:
        raise ValueError("claim_level must be one of: idea|prototype|validated|published")
    if not source_refs:
        raise ValueError("source_refs is required")
