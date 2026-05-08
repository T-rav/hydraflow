"""EventType ↔ frontend reducer parity check.

Every `EventType` member must either:
- have a `case 'value':` clause in the HydraFlowContext reducer, OR
- carry a `# frontend: backend-only — <reason of >= 10 chars>` comment
  marker on its enum line.

See `docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md` §4.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from _event_parity_parsers import (  # noqa: E402
    parse_backend_only_markers,
    parse_event_type_values,
    parse_reducer_cases,
)

EVENTS_PY = REPO_ROOT / "src" / "events.py"
REDUCER_JSX = REPO_ROOT / "src" / "ui" / "src" / "context" / "HydraFlowContext.jsx"


def test_every_event_type_is_handled_or_marked_backend_only() -> None:
    enum_values = parse_event_type_values(EVENTS_PY)
    reducer_cases = parse_reducer_cases(REDUCER_JSX)
    backend_only = parse_backend_only_markers(EVENTS_PY)

    handled = enum_values & reducer_cases
    tagged = enum_values & backend_only.keys()
    orphans = enum_values - handled - tagged

    if orphans:
        lines = "\n".join(f"  - {v}" for v in sorted(orphans))
        msg = (
            f"EventType values are neither handled in the reducer nor "
            f"tagged backend-only:\n{lines}\n\n"
            f"Fix by either:\n"
            f"  (a) adding `case 'value':` in {REDUCER_JSX.relative_to(REPO_ROOT)}, OR\n"
            f"  (b) adding `# frontend: backend-only — <reason>` (>=10 chars) "
            f"on the enum line in {EVENTS_PY.relative_to(REPO_ROOT)}.\n"
        )
        pytest.fail(msg)


def test_no_orphan_reducer_cases() -> None:
    """Reducer cases that don't match any EventType are likely typos."""
    enum_values = parse_event_type_values(EVENTS_PY)
    reducer_cases = parse_reducer_cases(REDUCER_JSX)
    # Reducer also handles redux-style action types like 'CONNECTED' — these
    # are intentionally NOT EventType members. Allowlist by uppercase shape.
    backend_actions = {c for c in reducer_cases if c == c.upper()}
    suspicious = reducer_cases - enum_values - backend_actions
    if suspicious:
        lines = "\n".join(f"  - '{c}'" for c in sorted(suspicious))
        msg = (
            f"Reducer cases that don't match any EventType (likely typos "
            f"or removed events):\n{lines}\n"
        )
        pytest.fail(msg)
