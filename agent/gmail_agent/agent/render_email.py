from __future__ import annotations

from pathlib import Path

from agent.paths import assert_within_agent_root


def render_email_pdf_stub(agent_root: Path, out_pdf: Path, title: str, body_text: str) -> None:
    # Placeholder: writes a .txt so you can test pipeline before adding PDF deps.
    assert_within_agent_root(agent_root, out_pdf)
    out_txt = out_pdf.with_suffix(".txt")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(f"{title}\n\n{body_text}\n", encoding="utf-8")
