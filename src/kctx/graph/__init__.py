"""M2 shadow-mode Dolt graph (moved under the kctx package; PORTING.md).

Importable both with the repo root on sys.path (flat modules during the
port) and standalone: the lazy fallback below adds the repo root only if
a flat import actually fails.
"""

import os
import sys
from pathlib import Path as _Path

try:  # pragma: no cover - exercised implicitly by every import below
    import errors  # noqa: F401
except ImportError:  # repo root not on sys.path: add it once
    _ROOT = _Path(__file__).resolve().parents[3]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
