from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

try:
    from ds_shared.compliance import detect_pii_signal  # type: ignore
except ModuleNotFoundError:
    shared_dir = Path(__file__).resolve().parents[2] / "shared"
    if str(shared_dir) not in sys.path:
        sys.path.insert(0, str(shared_dir))
    from ds_shared.compliance import detect_pii_signal  # type: ignore


def detect_pii(text: str) -> Optional[str]:
    return detect_pii_signal(text)
