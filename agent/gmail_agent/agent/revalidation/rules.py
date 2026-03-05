from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from agent.paths import Paths


DEFAULT_RULES: Dict[str, Any] = {
    "version": "rcr_2014_seed",
    "annual_expectation": {
        "credits_per_year": 50,
        "credits_per_5y": 250,
    },
    "activities": {
        # seed set only; expand from your RCR CPD activity table next
        "peer_review_paper_or_grant": {"credits": {"type": "per_item", "value": 1}},
        "full_paper_author": {"credits": {"type": "per_item", "value": 20}},
        "full_paper_coauthor": {"credits": {"type": "per_item", "value": 3}},
        "lecture_delivery": {"credits": {"type": "per_item", "value": 3}},
        "poster_author": {"credits": {"type": "per_item", "value": 3}},
        "case_report": {"credits": {"type": "per_item", "value": 3}},
        "formal_educational_activities": {"credits": {"type": "per_hour", "value": 1}},
        "self_directed_learning": {"credits": {"type": "per_hour", "value": 1}},
    },
}


def rules_path(p: Paths) -> Path:
    return p.rules_dir / "cpd_rules.yaml"


def load_rules(p: Paths) -> Dict[str, Any]:
    rp = rules_path(p)
    with rp.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_rules(p: Paths, rules: Dict[str, Any]) -> None:
    rp = rules_path(p)
    rp.parent.mkdir(parents=True, exist_ok=True)
    with rp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(rules, f, sort_keys=False)


def init_rules_if_missing(p: Paths) -> None:
    rp = rules_path(p)
    if not rp.exists():
        save_rules(p, DEFAULT_RULES)


def rules_show(p: Paths) -> None:
    rules = load_rules(p)
    ae = rules.get("annual_expectation", {})
    acts = rules.get("activities", {})

    print(f"rules file: {rules_path(p)}")
    print(f"expected: {ae.get('credits_per_year')} / year, {ae.get('credits_per_5y')} / 5 years")
    print(f"activities: {len(acts)}")
    for k in sorted(acts.keys()):
        c = acts[k]["credits"]
        print(f"- {k}: {c['type']} = {c['value']}")
