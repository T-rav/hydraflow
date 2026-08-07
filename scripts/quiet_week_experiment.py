#!/usr/bin/env python3
"""Quiet-week experiment runner — I/O shell over the decay engine (#10822).

The pure engine (`stillness.decay`) shipped with nothing running it. This is the
missing half: an ON-DEMAND runner (like `scripts/mutation_gauntlet.py` /
`scripts/calibrate_finders.py`, NOT a loop) you invoke after a freeze week to ask
the acceptance question — did mutating activity decay to the sensing floor, or did
the factory keep churning as its own disturbance source (hunting)?

It reads the on-disk pipeline event log (`events.jsonl`), folds the *mutating*
events (opened work, opened PRs, merges) into a daily series split by origin, and
runs `fit_decay`. The origin split is the crux and is a documented heuristic:

  * an `issue_created` whose labels carry NO factory marker
    (`hydraflow-find` / `auto-agent` / `auto-decomposed-child` / …) is treated as
    EXTERNAL — a genuine, human-filed disturbance the freeze allows;
  * everything else (factory-generated issues, all PRs and merges) is
    SELF-ORIGINATED — the churn a quiet week must see decay.

The heuristic is coarse (a human could file a labelled issue), so the runner
prints the split it used; refine it as event payloads carry richer provenance.
Read-only: it never writes the event log or files anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stillness.decay import (  # noqa: E402
    MUTATING_EVENT_TYPES,
    ActivityEvent,
    daily_activity,
    fit_decay,
)

#: Labels that mark an issue as factory-generated (self-originated), not a
#: genuine external disturbance. Kept small and greppable; extend as needed.
_FACTORY_ISSUE_MARKERS = (
    "hydraflow-find",
    "auto-agent",
    "auto-decomposed-child",
    "hydraflow-epic-child",
    "hydraflow-plan",
    "hydraflow-ready",
)


def _labels_of(data: object) -> list[str]:
    if isinstance(data, dict):
        labels = data.get("labels")
        if isinstance(labels, list):
            return [str(label) for label in labels]
    return []


def classify_external(event_type: str, data: object) -> bool:
    """True for a genuine external (human-driven) disturbance.

    Only a human-filed issue counts — an ``issue_created`` with no factory-marker
    label. Factory-generated issues and all PR/merge activity are self-originated.
    """
    if event_type != "issue_created":
        return False
    labels = _labels_of(data)
    return not any(
        marker in label for label in labels for marker in _FACTORY_ISSUE_MARKERS
    )


def _event_day(iso_timestamp: str) -> date | None:
    try:
        return datetime.fromisoformat(iso_timestamp).date()
    except (ValueError, TypeError):
        return None


def load_activity(event_log: Path, *, end: date, days: int) -> list[ActivityEvent]:
    """Read `events.jsonl` and map mutating events to classified ActivityEvents.

    ``end`` is the last day of the window; day 0 is ``end - (days - 1)``.
    """
    start = date.fromordinal(end.toordinal() - (days - 1))
    out: list[ActivityEvent] = []
    for raw_line in event_log.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        event_type = str(event.get("type", ""))
        if event_type not in MUTATING_EVENT_TYPES:
            continue
        day = _event_day(str(event.get("timestamp", "")))
        if day is None:
            continue
        day_index = day.toordinal() - start.toordinal()
        if not 0 <= day_index < days:
            continue
        out.append(
            ActivityEvent(
                day_index=day_index,
                event_type=event_type,
                external=classify_external(event_type, event.get("data")),
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quiet-week decay experiment (#10822)")
    parser.add_argument(
        "--event-log", type=Path, required=True, help="Path to events.jsonl"
    )
    parser.add_argument(
        "--days", type=int, default=7, help="Freeze-window length in days"
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Last day of the window (ISO); defaults to today",
    )
    parser.add_argument(
        "--floor", type=float, default=1.0, help="Read-only sensing floor"
    )
    args = parser.parse_args(argv)

    if not args.event_log.is_file():
        print(f"event log not found: {args.event_log}", file=sys.stderr)
        return 2

    end = args.end_date or datetime.now().date()  # noqa: DTZ005 — local experiment date
    events = load_activity(args.event_log, end=end, days=args.days)
    series = daily_activity(events, days=args.days)
    fit = fit_decay(series, floor=args.floor)

    print(f"Quiet-week decay experiment — {args.days}d window ending {end}")
    print(f"  verdict:        {fit.verdict.value.upper()}")
    print(f"  decay rate:     {fit.decay_rate:.3f}/day (r²={fit.r_squared:.2f})")
    print(f"  self-sustaining:{fit.self_sustaining}")
    print("  daily activity (self / external):")
    for day in series:
        print(f"    day {day.day_index}: {day.self_originated} / {day.external}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
