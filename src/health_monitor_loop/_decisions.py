"""The health-monitor decision journal.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547). The append-only ``decisions.jsonl`` audit trail
every auto-adjustment writes: ID minting, atomic append, load, and the
in-place verification update.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from audit_chain import AuditChain

logger = logging.getLogger("hydraflow.health_monitor_loop")


def _next_decision_id(_decisions_dir: Path) -> str:
    """Return a unique decision ID using UUID."""
    return f"adj-{uuid.uuid4().hex[:8]}"


def _write_decision(decisions_dir: Path, record: dict[str, Any]) -> None:
    try:
        decisions_dir.mkdir(parents=True, exist_ok=True)
        # Hash-chained append (CH-1, #9729): stamps prev_hash/record_hash so
        # out-of-band edits to the decision trail are detectable.
        AuditChain(decisions_dir / "decisions.jsonl").append(record)
    except (OSError, ValueError):
        # Disk full, permission, or other I/O error — plus ValueError from
        # the chain's serialization paths (incl. json.JSONDecodeError from
        # secret scrubbing). The health monitor loop must not abort its tick
        # over a single failed decision write.
        logger.warning(
            "Failed to persist health decision to %s", decisions_dir, exc_info=True
        )


def _load_decisions(decisions_dir: Path) -> list[dict[str, Any]]:
    decisions_file = decisions_dir / "decisions.jsonl"
    if not decisions_file.exists():
        return []
    try:
        lines = decisions_file.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        rec: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            rec = json.loads(line)
        if rec:
            records.append(rec)
    return records


def _update_decision(
    decisions_dir: Path, decision_id: str, updates: dict[str, Any]
) -> None:
    """Atomically rewrite decisions.jsonl updating the record matching decision_id.

    This is the sanctioned amendment path for the decision audit trail
    (verification outcomes are back-filled after the observation window).
    ``AuditChain.rewrite`` re-chains the hash fields from the amended record
    forward, so the trail stays verifiable while out-of-band edits still
    break the chain (CH-1, #9729).
    """
    # Anti-laundering guard: _load_decisions silently drops unparseable
    # lines, so rewriting a BROKEN stream would erase tamper evidence
    # before the RunsGC verifier ever sees it. Amendments only proceed on
    # a clean chain; a broken one is left byte-for-byte for detection.
    decisions_file = decisions_dir / "decisions.jsonl"
    if decisions_file.exists() and not AuditChain(decisions_file).verify().ok:
        logger.error(
            "decisions.jsonl chain is broken — amendment for %s aborted "
            "to preserve tamper evidence (RunsGC will alert)",
            decision_id,
        )
        return
    records = _load_decisions(decisions_dir)
    updated = False
    for record in records:
        if record.get("decision_id") == decision_id:
            record.update(updates)
            updated = True
            break
    if not updated:
        return
    decisions_dir.mkdir(parents=True, exist_ok=True)
    AuditChain(decisions_dir / "decisions.jsonl").rewrite(records)
