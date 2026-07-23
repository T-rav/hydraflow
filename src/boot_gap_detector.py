"""Boot-time detector for a factory-down gap in ``events.jsonl`` (#10009).

Nothing inside the running process notices when the process itself is down —
that's what the external liveness watchdog
(``scripts/factory_liveness_watchdog.py``) is for. This module is the
retroactive, in-process half: at the *next* boot, compare the timestamp of
the last persisted event against "now". A large gap means the process was
down (crash, host reboot, deploy window) for roughly that long, even though
nothing was watching at the time. One ``SYSTEM_ALERT`` is published so the
dashboard shows "factory was down ~Xh" instead of the outage passing
silently.

Deliberately cheap and side-effect-free: :func:`last_event_timestamp` only
reads the tail of the log (a corrupt/huge file never blocks boot), and
:func:`compute_boot_gap_alert` is a pure function of its three inputs so the
decision logic is trivial to unit test without any I/O.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from models import SystemAlertPayload

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("hydraflow.boot_gap_detector")

#: Trailing lines scanned (from the end, backwards) looking for one
#: parseable event. Bounds the cost on a large log and tolerates a corrupt
#: final line or two without blinding the check entirely.
_MAX_TAIL_LINES = 200


def last_event_timestamp(path: Path) -> datetime | None:
    """Return the timestamp of the most recent parseable event in *path*.

    Returns ``None`` when the file is missing, unreadable, empty, or every
    line in the scanned tail fails to parse (e.g. all-corrupt, or entries
    missing a ``timestamp`` field).
    """
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.debug("Could not read %s for boot-gap check", path, exc_info=True)
        return None

    lines = text.splitlines()
    for line in reversed(lines[-_MAX_TAIL_LINES:]):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        ts = record.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            parsed = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    return None


def compute_boot_gap_alert(
    *,
    last_event_at: datetime | None,
    boot_at: datetime,
    threshold_seconds: float,
) -> SystemAlertPayload | None:
    """Pure decision: a SYSTEM_ALERT payload if the gap exceeds the threshold.

    ``last_event_at=None`` (no prior events — fresh install, or a log that
    rotated away every prior line) never alerts: there is nothing to compare
    against, and a fresh install is not downtime. A negative gap (clock skew,
    or an event timestamped after ``boot_at`` due to test/replay artifacts)
    also never alerts.
    """
    if last_event_at is None:
        return None
    if last_event_at.tzinfo is None:
        last_event_at = last_event_at.replace(tzinfo=UTC)
    gap_seconds = (boot_at - last_event_at).total_seconds()
    if gap_seconds <= threshold_seconds:
        return None

    gap_hours = gap_seconds / 3600
    return SystemAlertPayload(
        message=(
            f"factory was down ~{gap_hours:.1f}h (last event at "
            f"{last_event_at.isoformat()}, booted at {boot_at.isoformat()})"
        ),
        source="boot_gap_detector",
        severity="warning",
    )
