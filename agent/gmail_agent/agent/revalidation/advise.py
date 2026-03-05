from __future__ import annotations

from pathlib import Path

from agent.paths import Paths, assert_within_agent_root
from agent.revalidation.rules import load_rules


def _scan_source_evidence_paths(source_evidence: Path) -> list[str]:
    if not source_evidence.exists():
        return []
    return [str(p.relative_to(source_evidence)) for p in source_evidence.rglob("*") if p.is_file()]


def advise(p: Paths) -> None:
    rules = load_rules(p)
    out = p.index_dir / "advice.md"
    assert_within_agent_root(p.agent_root, out)

    evidence_files = _scan_source_evidence_paths(p.source_evidence)
    evidence_text = "\n".join(f"- {x}" for x in sorted(evidence_files)[:200])

    ae = rules.get("annual_expectation", {})
    acts = rules.get("activities", {})

    lines = []
    lines.append("Revalidation advice\n")
    lines.append(f"- CPD expectation: {ae.get('credits_per_year')} credits/year; {ae.get('credits_per_5y')} credits/5 years\n")
    lines.append(f"- Known CPD rule keys loaded: {len(acts)}\n")
    lines.append("\nEvidence files seen under source/evidence (first 200):\n")
    lines.append(evidence_text if evidence_text else "- (none)\n")
    lines.append("\nNext steps (manual, minimal):\n")
    lines.append("- expand cpd_rules.yaml to include the full RCR activity table\n")
    lines.append("- enable Gmail scanning once rules are complete\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")
