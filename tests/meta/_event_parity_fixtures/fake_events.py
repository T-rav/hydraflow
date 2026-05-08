"""Synthetic fixture — fake EventType enum with backend-only markers.

Tests the marker-grammar parser:
- ORPHAN_NO_REASON: marker without dash + reason → not tagged
- ORPHAN_SHORT_REASON: marker with too-short reason → not tagged
- ORPHAN_VALID: well-formed marker → tagged
"""

from enum import StrEnum


class EventType(StrEnum):
    PHASE_CHANGE = "phase_change"
    ORPHAN_NO_REASON = "orphan_no_reason"  # frontend: backend-only
    ORPHAN_SHORT_REASON = "orphan_short"  # frontend: backend-only — too short
    ORPHAN_VALID = (
        "orphan_valid"  # frontend: backend-only — JSONL audit only, never in UI
    )
    NEW_THING = "new_thing"
