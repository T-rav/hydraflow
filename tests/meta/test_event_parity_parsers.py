"""Meta-tests for `src/_event_parity_parsers.py`."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from _event_parity_parsers import (  # noqa: E402
    BackendOnlyEntry,
    parse_backend_only_markers,
    parse_event_type_values,
    parse_reducer_cases,
)

FIXTURES = Path(__file__).parent / "_event_parity_fixtures"


def test_parse_event_type_values() -> None:
    values = parse_event_type_values(FIXTURES / "fake_events.py")
    assert values == {
        "phase_change",
        "orphan_no_reason",
        "orphan_short",
        "orphan_valid",
        "new_thing",
    }


def test_parse_reducer_cases() -> None:
    cases = parse_reducer_cases(FIXTURES / "fake_reducer.jsx")
    assert cases == {"phase_change"}


def test_parse_backend_only_markers_filters_invalid() -> None:
    markers = parse_backend_only_markers(FIXTURES / "fake_events.py")
    assert "orphan_valid" in markers
    assert markers["orphan_valid"].reason.startswith("JSONL audit only")
    assert "orphan_no_reason" not in markers
    assert "orphan_short" not in markers


def test_backend_only_marker_carries_lineno() -> None:
    markers = parse_backend_only_markers(FIXTURES / "fake_events.py")
    entry = markers["orphan_valid"]
    assert isinstance(entry, BackendOnlyEntry)
    assert entry.lineno > 0


def test_backend_only_accepts_ascii_hyphen() -> None:
    """The marker grammar accepts both em-dash (—) and ASCII hyphen (-)."""
    text = (
        "from enum import StrEnum\n"
        "class EventType(StrEnum):\n"
        '    HYPH_OK = "hyph_ok"  # frontend: backend-only - long enough reason here\n'
    )
    fake = FIXTURES / "fake_events_hyphen.py"
    fake.write_text(text)
    try:
        markers = parse_backend_only_markers(fake)
        assert "hyph_ok" in markers
        assert "long enough" in markers["hyph_ok"].reason
    finally:
        fake.unlink()
