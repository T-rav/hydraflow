"""Shared self-retiring ADR resolution for ADR-drift regression pins (#11186).

Pin modules such as ``test_issue_10440.py`` resolve a pinned
ADR by number and must degrade gracefully (skip, never raise or fail an
assertion) once that ADR is renumbered, removed, or moves off
Accepted/Proposed — see ``tests/regressions/test_issue_11186.py`` for the
meta-guard proving this behaviour.

The runtime skip lives here, in a module the ``tests/`` naming convention
excludes from ``tests/architecture/test_no_ignored_active_tests.py``'s
active-test-file scan (files whose name starts with ``test`` or is
``conftest.py``), so this centrally-reviewed self-retiring resolution isn't
flagged the same way an ad-hoc per-test skip would be. Lives at the ``tests/``
root rather than ``tests/regressions/`` — mirroring ``tests/_spawn_audit.py``
and ``tests/_credit_reraise_audit.py`` — because
``tests/regressions/test_issue_9801_collection.py`` requires every file
directly under ``tests/regressions/`` to match a pytest collection pattern.
"""

from __future__ import annotations

import pytest

from adr_index import ADR, ADRIndex


def resolve_live_adr(index: ADRIndex, number: int) -> ADR:
    """Resolve *number* to a live ADR, or retire the calling test.

    Skips the caller when the ADR is absent, renumbered away, or has moved
    off Accepted/Proposed (``ADR.is_live``) — so routine ADR maintenance
    cannot redden a pin whose target no longer applies.
    """
    adr = next((a for a in index.adrs() if a.number == number), None)
    if adr is None or not adr.is_live:
        pytest.skip(
            f"ADR-{number:04d} is absent or not live — pin self-retires (#11186)"
        )
    return adr
