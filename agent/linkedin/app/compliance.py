from __future__ import annotations

import sys
from pathlib import Path

try:
    from ds_shared.compliance import (  # type: ignore
        REQUIRED_CLAIM_LEVELS,
        assert_no_pii,
        assert_required_metadata,
        contains_pii,
    )
except ModuleNotFoundError:
    shared_dir = Path(__file__).resolve().parents[2] / "shared"
    if str(shared_dir) not in sys.path:
        sys.path.insert(0, str(shared_dir))
    from ds_shared.compliance import (  # type: ignore
        REQUIRED_CLAIM_LEVELS,
        assert_no_pii,
        assert_required_metadata,
        contains_pii,
    )

__all__ = [
    "REQUIRED_CLAIM_LEVELS",
    "contains_pii",
    "assert_no_pii",
    "assert_required_metadata",
]
