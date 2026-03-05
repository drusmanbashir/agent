from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass(frozen=True)
class Config:
    source_root: Path
    agent_root: Path
    llm_provider: str = "openai"
    llm_model: str = ""
    gmail_enabled: bool = False


def load_config(path: Path) -> Config:
    with path.open("r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}

    paths = raw.get("paths", {})
    llm = raw.get("llm", {})
    gmail = raw.get("gmail", {})

    return Config(
        source_root=Path(paths["source_root"]),
        agent_root=Path(paths["agent_root"]),
        llm_provider=str(llm.get("provider", "openai")),
        llm_model=str(llm.get("model", "")),
        gmail_enabled=bool(gmail.get("enabled", False)),
    )
