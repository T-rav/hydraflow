"""HydraFlow Principles audit tool.

Reads ADR-0044 check tables and scores a target repository against the ten
principles defined there. See `docs/adr/0044-hydraflow-principles.md` for the
contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ``make audit`` runs ``python -m scripts.hydraflow_audit .`` with only the repo
# ROOT on ``sys.path`` (not ``src``). The P10 checks import the pure false-close
# classifier, which lives at ``src/false_close.py`` (#10365) because the factory
# container runs ``PYTHONPATH=src`` and ``src`` must NEVER import from
# ``scripts``. Add this checkout's ``src`` to the path — the same bootstrap
# pattern many ``scripts/*.py`` already use — so ``from false_close import ...``
# resolves here without dragging the audit package into ``scripts``. This
# ``__init__`` runs before any submodule (including ``checks.p10_tdd``) is
# imported, so the path is ready before the first classifier import. ``src``
# exposes only unique top-level module names (``false_close`` etc.), so this
# shadows nothing the audit package's stdlib/relative imports depend on.
_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if _SRC_DIR.is_dir():
    _src = str(_SRC_DIR)
    if _src not in sys.path:
        sys.path.insert(0, _src)
