"""Staleness evaluator for wiki entries.

Pure functions — no I/O, no LLM calls. Resolves valid_to expressions
and classifies entries as current / expired / superseded.

valid_to grammar (V1 — intentionally minimal, no DSL):
  - ISO8601 date (2026-12-31) or datetime (2026-12-31T00:00:00+00:00)
  - Relative duration: Nd (days), Nmo (months≈30d), Ny (years≈365d)
  - None — indefinite
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta


class ParseError(ValueError):
    """Raised when valid_to cannot be parsed."""


_DURATION_RE = re.compile(r"^(\d+)(d|mo|y)$")


def parse_valid_to(raw: str | None, *, now: datetime) -> str | None:
    """Resolve a valid_to expression to an absolute ISO8601 string.

    Returns None if raw is None or empty (indefinite).
    Raises ParseError if raw cannot be parsed.
    """
    if raw is None or raw == "":
        return None

    match = _DURATION_RE.match(raw)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        if n <= 0:
            raise ParseError(f"valid_to duration must be positive: {raw!r}")
        days = {"d": n, "mo": n * 30, "y": n * 365}[unit]
        return (now + timedelta(days=days)).isoformat()

    # Try parsing as ISO8601
    try:
        candidate = raw
        # Accept plain date (2026-12-31) by appending midnight UTC
        if "T" not in candidate and len(candidate) == 10:
            candidate = f"{candidate}T00:00:00+00:00"
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.isoformat()
    except ValueError as exc:
        raise ParseError(f"valid_to must be ISO8601 or duration: {raw!r}") from exc
