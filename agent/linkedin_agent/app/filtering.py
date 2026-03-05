from __future__ import annotations

import math
import re
from collections import Counter

from .models import ScoredItem, SourceItem
from .profile import DOCSMART_PROFILE


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def keyword_score(text: str, keywords: list[str]) -> float:
    low = text.lower()
    return sum(1.0 for kw in keywords if kw in low)


def semantic_score(text: str, profile_terms: list[str]) -> float:
    text_vec = Counter(_tokens(text))
    profile_vec = Counter(_tokens(" ".join(profile_terms)))
    dot = sum(text_vec[t] * profile_vec[t] for t in text_vec)
    text_norm = math.sqrt(sum(v * v for v in text_vec.values()))
    profile_norm = math.sqrt(sum(v * v for v in profile_vec.values()))
    if text_norm == 0 or profile_norm == 0:
        return 0.0
    return dot / (text_norm * profile_norm)


def score_item(item: SourceItem) -> ScoredItem:
    kw = keyword_score(item.content + "\n" + item.title, DOCSMART_PROFILE["keywords"])
    sem = semantic_score(item.content + "\n" + item.title, DOCSMART_PROFILE["keywords"] + DOCSMART_PROFILE["pillars"])
    total = kw + (3.0 * sem)
    return ScoredItem(item=item, keyword_score=kw, semantic_score=sem, total_score=total)
