# agent/revalidation/gmail_advisor.py
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from agent.gmail import fetch_headers_last_12_months
from agent.paths import assert_within_agent_root
from agent.revalidation.triage import triage, classify_bucket


def _hdr_to_dict(h: Any) -> dict:
    # Accept either dataclass-like objects or plain objects
    if is_dataclass(h):
        d = asdict(h)
        # normalise common keys if needed
        return {
            "date": d.get("date", ""),
            "from": d.get("sender", d.get("from_", d.get("from", ""))),
            "subject": d.get("subject", ""),
        }

    return {
        "date": getattr(h, "date", ""),
        "from": getattr(h, "sender", getattr(h, "from_", getattr(h, "from", ""))),
        "subject": getattr(h, "subject", ""),
    }


def run_gmail_advisor(
    agent_root: Path,
    year: int,
    evidence_dir: Path,
    guidelines_dir: Path,
    oauth_client_json: Path,
    token_json: Path,
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    evidence_files = [
        str(p.relative_to(evidence_dir))
        for p in evidence_dir.rglob("*")
        if p.is_file()
    ]

    guideline_files = [
        str(p.relative_to(guidelines_dir))
        for p in guidelines_dir.rglob("*")
        if p.is_file()
    ]

    raw_headers = fetch_headers_last_12_months(
        oauth_client_json=oauth_client_json,
        token_json=token_json,
    )

    included: list[dict] = []
    needs_review: list[dict] = []

    for h in raw_headers:
        d = _hdr_to_dict(h)
        sender = d.get("from", "")
        subject = d.get("subject", "")

        m = triage(sender, subject)  # returns TriageMatch(verdict, reason)

        if m.verdict == "include":
            d["bucket"] = classify_bucket(sender, subject)
            d["triage_reason"] = m.reason
            included.append(d)
        elif m.verdict == "needs_review":
            d["bucket"] = classify_bucket(sender, subject)
            d["triage_reason"] = m.reason
            needs_review.append(d)

    # keep manageable for manual inspection + LLM context
    needs_review = needs_review[:200]

    needs_review_path = out_dir / f"gmail_needs_review_{year}.json"
    assert_within_agent_root(agent_root, needs_review_path)
    needs_review_path.write_text(json.dumps(needs_review, indent=2), encoding="utf-8")

    payload = {
        "year": year,
        "evidence_files": evidence_files,
        "guideline_files": guideline_files,
        "gmail_headers": included,  # INCLUDED ONLY
        "needs_review_file": str(needs_review_path),
        "instruction": (
            "Identify which emails are relevant as CPD or revalidation evidence "
            "and advise what to save into the evidence folder."
        ),
    }

    out_path = out_dir / f"gmail_payload_{year}.json"
    assert_within_agent_root(agent_root, out_path)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path

