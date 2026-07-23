"""Thin source adapters for the intervention tally (#10369).

Materialize raw ``InterventionSignal``s from the human touches the factory
ALREADY emits — this package never instruments new capture points, it
aggregates existing streams (spec: "it aggregates records the factory already
emits"). NOT part of the pure classifier; these are the I/O boundary, mirror
of ``escape.detect``'s thin git adapters.

v1 sources:

* **HITL escalation lifecycle** — resolution actions on the persisted event
  log (``EventType.HITL_UPDATE``): the human-in-the-loop resolutions
  (``resolved``/``approved``/``denied``/…). The escalation RAISE is the system
  asking, not a human touch, so only resolutions are sensed.
* **Dashboard control-route actions** — governor start/stop on the event log
  (``EventType.ORCHESTRATOR_STATUS``): a human pausing/resuming the fleet from
  the dashboard. An event whose ``data.source == "cli"`` is re-sourced to the
  ``cli`` intervention source so ``/hf`` admin commands driving the same
  routes are attributed correctly.
* **Steering directives** — the per-issue ``SteeringState`` the factory
  already parses (ADR-0099 #4): ``flow`` transitions and free-text guidance.

Known v1 blind spot (noted in the report, not sensed): manual ``git`` surgery
on the repo outside the factory's surfaces.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from intervention.models import InterventionSignal, InterventionSource

#: HITL_UPDATE ``action`` values that are genuine human resolutions (not the
#: loop's own ``hitl_run`` running/done lifecycle noise). Keys are matched
#: against the mechanical map in ``intervention.classify`` (``hitl:<action>``).
_HITL_RESOLUTION_ACTIONS: frozenset[str] = frozenset(
    {
        "resolved",
        "approved",
        "approve",
        "denied",
        "deny",
        "rejected",
        "redirected",
        "reassigned",
        "reverted",
        "quality_reject",
        "unstuck",
    }
)

#: ORCHESTRATOR_STATUS ``status`` → control-route ``kind`` (governor actions).
_ORCH_STATUS_KIND: dict[str, str] = {
    "stopped": "abort",
    "paused": "pause",
    "running": "resume",
}


class _SteeringLike(Protocol):
    """Duck-typed ``SteeringState`` (avoid a heavy cross-import here)."""

    guidance: str | None
    flow: str
    redo_phase: str | None
    redo_count: int
    last_applied_ts: str | None


def _after(ts: str, since_ts: str) -> bool:
    """True when ISO *ts* is strictly newer than *since_ts* (string-safe).

    Both are ISO-8601, which sorts lexicographically in chronological order, so
    a plain string compare is a correct cursor test without parsing. An empty
    *since_ts* (fresh cursor) admits nothing here — priming is the loop's job.
    """
    return bool(ts) and bool(since_ts) and ts > since_ts


def signals_from_event_log(
    event_log_path: Path, since_ts: str
) -> list[InterventionSignal] | None:
    """Sense HITL resolutions + governor control actions from the event log.

    Returns ``None`` on a read failure (so the caller distinguishes "nothing
    new" from "couldn't read"); ``[]`` when the log has no new human touches.
    Only events strictly newer than *since_ts* are considered (cursor dedup).
    """
    if not event_log_path.exists():
        return []
    try:
        text = event_log_path.read_text(encoding="utf-8")
    except OSError:
        return None

    signals: list[InterventionSignal] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        signal = _signal_from_event(event, since_ts)
        if signal is not None:
            signals.append(signal)
    return signals


def _signal_from_event(
    event: dict[str, Any], since_ts: str
) -> InterventionSignal | None:
    """Map one persisted event dict to a signal, or ``None`` if not a touch."""
    ts = str(event.get("timestamp", ""))
    if not _after(ts, since_ts):
        return None
    etype = str(event.get("type", ""))
    data = event.get("data")
    data = data if isinstance(data, dict) else {}

    if etype == "hitl_update":
        action = str(data.get("action", ""))
        if action not in _HITL_RESOLUTION_ACTIONS:
            return None
        issue = data.get("issue")
        origin = str(data.get("origin", "") or data.get("source", "") or "hitl")
        return InterventionSignal(
            source="hitl",
            kind=action,
            ts=ts,
            loop_or_workflow=origin,
            issue_or_pr=_ref_str(issue),
            ref=f"hitl:{issue}:{ts}",
            free_text=str(data.get("reason", "")),
        )

    if etype == "orchestrator_status":
        status = str(data.get("status", ""))
        kind = _ORCH_STATUS_KIND.get(status)
        if kind is None:
            return None
        # A ``/hf`` CLI command driving the same route tags data.source=cli.
        source: InterventionSource = (
            "cli" if str(data.get("source", "")) == "cli" else "control-route"
        )
        return InterventionSignal(
            source=source,
            kind=kind,
            ts=ts,
            loop_or_workflow="orchestrator",
            ref=f"{source}:{status}:{ts}",
        )

    return None


def signals_from_steering(
    steering: Mapping[str, _SteeringLike],
    since_ts: str,
    *,
    model_version_context: str = "",
) -> list[InterventionSignal]:
    """Sense steering directives applied since *since_ts* (pure over the map).

    One signal per issue whose ``last_applied_ts`` is newer than the cursor.
    ``flow`` transitions map mechanically (abort/paused → unstick, redo →
    objective-correction); a plain running directive carrying free-text
    ``guidance`` becomes a free-text signal the classifier may send to the
    cheap LLM. Directives with neither a mechanical flow nor guidance are not
    interventions and are skipped.
    """
    signals: list[InterventionSignal] = []
    for issue, st in steering.items():
        applied = str(getattr(st, "last_applied_ts", "") or "")
        if not _after(applied, since_ts):
            continue
        flow = str(getattr(st, "flow", "") or "running")
        guidance = str(getattr(st, "guidance", "") or "")
        redo_phase = getattr(st, "redo_phase", None)

        if flow == "abort":
            kind, free_text = "abort", guidance
        elif flow == "paused":
            kind, free_text = "paused", guidance
        elif redo_phase:
            kind, free_text = "redo", guidance
        elif guidance.strip():
            kind, free_text = "guidance", guidance
        else:
            continue

        signals.append(
            InterventionSignal(
                source="steering",
                kind=kind,
                ts=applied,
                loop_or_workflow="pipeline",
                issue_or_pr=str(issue),
                ref=f"steering:{issue}:{applied}",
                free_text=free_text,
                model_version_context=model_version_context,
            )
        )
    return signals


def active_loop_count_from_event_log(event_log_path: Path) -> int:
    """Count distinct worker loops seen heartbeating in the event log.

    A concrete, sensed proxy for "median concurrently-active worker loops"
    (the loops-per-governor numerator): the distinct ``worker`` values across
    ``background_worker_status`` events. Reuses the same event stream the
    intervention sources read; ``0`` on any read failure or empty log.
    """
    if not event_log_path.exists():
        return 0
    try:
        text = event_log_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    workers: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if str(event.get("type", "")) != "background_worker_status":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        worker = str(data.get("worker", ""))
        if worker:
            workers.add(worker)
    return len(workers)


def _ref_str(value: Any) -> str:
    return "" if value is None else str(value)
