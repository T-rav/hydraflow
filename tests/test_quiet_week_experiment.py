"""Tests for the quiet-week experiment runner + its event adapter (#10822 wiring).

Loads the script via ``importlib`` (like ``tests/test_calibrate_finders.py``) so
it works regardless of whether ``scripts`` is on ``sys.path``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from stillness.decay import ActivityEvent, daily_activity  # noqa: E402

_SCRIPT = Path(__file__).parent.parent / "scripts" / "quiet_week_experiment.py"
_spec = importlib.util.spec_from_file_location("quiet_week_experiment", _SCRIPT)
assert _spec and _spec.loader
qwe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qwe)


# --- pure adapter: daily_activity -----------------------------------------


def test_daily_activity_folds_mutating_events_by_day_and_origin() -> None:
    events = [
        ActivityEvent(0, "pr_created", external=False),
        ActivityEvent(0, "merge_update", external=False),
        ActivityEvent(1, "issue_created", external=True),  # human-filed
        ActivityEvent(1, "issue_created", external=False),  # factory
    ]
    series = daily_activity(events, days=3)
    assert [d.day_index for d in series] == [0, 1, 2]
    assert (series[0].self_originated, series[0].external) == (2, 0)
    assert (series[1].self_originated, series[1].external) == (1, 1)
    assert (series[2].self_originated, series[2].external) == (0, 0)  # zero-filled tail


def test_daily_activity_drops_non_mutating_and_out_of_window_events() -> None:
    events = [
        ActivityEvent(0, "worker_update", external=False),  # not mutating
        ActivityEvent(9, "pr_created", external=False),  # outside window
        ActivityEvent(0, "pr_created", external=False),  # counted
    ]
    series = daily_activity(events, days=3)
    assert sum(d.total for d in series) == 1


# --- runner classification: external only for human-filed issues -----------


def test_only_a_human_filed_issue_is_external() -> None:
    assert qwe.classify_external("issue_created", {"labels": ["bug"]}) is True
    assert (
        qwe.classify_external("issue_created", {"labels": ["hydraflow-find"]}) is False
    )
    assert (
        qwe.classify_external("issue_created", {"labels": ["auto-agent", "P2"]})
        is False
    )
    # PRs and merges are always self-originated, regardless of labels.
    assert qwe.classify_external("pr_created", {"labels": ["bug"]}) is False
    assert qwe.classify_external("merge_update", {}) is False


def test_load_activity_reads_events_jsonl_over_the_window(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    rows = [
        {"type": "pr_created", "timestamp": "2026-08-01T09:00:00+00:00", "data": {}},
        {
            "type": "issue_created",
            "timestamp": "2026-08-02T09:00:00+00:00",
            "data": {"labels": ["bug"]},
        },
        {
            "type": "worker_update",
            "timestamp": "2026-08-02T10:00:00+00:00",
            "data": {},
        },  # dropped
        {
            "type": "merge_update",
            "timestamp": "2026-07-01T09:00:00+00:00",
            "data": {},
        },  # before window
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    events = qwe.load_activity(
        log, end=date(2026, 8, 7), days=7
    )  # window: 08-01..08-07
    assert len(events) == 2  # the PR + the human issue; worker/merge dropped
    by_day = {(e.day_index, e.event_type): e.external for e in events}
    assert by_day[(0, "pr_created")] is False  # 08-01 is day 0
    assert by_day[(1, "issue_created")] is True  # 08-02 is day 1, human-filed


def test_load_activity_tolerates_a_malformed_line(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    log.write_text(
        'not json\n{"type": "pr_created", "timestamp": "2026-08-01T00:00:00+00:00", "data": {}}\n',
        encoding="utf-8",
    )
    events = qwe.load_activity(log, end=date(2026, 8, 1), days=1)
    assert len(events) == 1
