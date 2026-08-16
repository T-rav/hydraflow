"""Unit tests for the #11298 backlog-budget retirement engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backlog_budget import retirement_picks

NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)


def _issue(number: int, *labels: str, age_days: float = 10.0) -> dict:
    created = NOW - timedelta(days=age_days)
    return {
        "number": number,
        "title": f"issue {number}",
        "createdAt": created.isoformat().replace("+00:00", "Z"),
        "labels": [{"name": name} for name in labels],
    }


def test_under_budget_retires_nothing() -> None:
    issues = [_issue(i, "hydraflow-find") for i in range(1, 6)]
    assert retirement_picks(issues, budget=10, min_age_days=2, now=NOW) == []


def test_overage_retires_oldest_first() -> None:
    issues = [
        _issue(1, "hydraflow-find", age_days=30),
        _issue(2, "hydraflow-find", age_days=20),
        _issue(3, "hydraflow-find", age_days=10),
    ]
    picks = retirement_picks(issues, budget=2, min_age_days=2, now=NOW)
    assert [p.number for p in picks] == [1]


def test_protected_labels_never_picked_nor_counted() -> None:
    issues = [
        _issue(1, "hydraflow-find", "human-required", age_days=30),
        _issue(2, "hydraflow-plan", "hydraflow-epic-child", age_days=30),
        _issue(3, "hydraflow-find", "P1", age_days=30),
        _issue(4, "hydraflow-ready", age_days=30),
        _issue(5, "hydraflow-find", age_days=30),
    ]
    # Advisory population is just #5 -> under any budget >= 1.
    assert retirement_picks(issues, budget=1, min_age_days=2, now=NOW) == []


def test_grace_period_exempts_fresh_filings() -> None:
    issues = [
        _issue(1, "hydraflow-find", age_days=1.0),
        _issue(2, "hydraflow-find", age_days=0.5),
        _issue(3, "hydraflow-find", age_days=5.0),
    ]
    picks = retirement_picks(issues, budget=1, min_age_days=2, now=NOW)
    assert [p.number for p in picks] == [3]


def test_per_cycle_cap() -> None:
    issues = [_issue(i, "hydraflow-find", age_days=30) for i in range(1, 40)]
    picks = retirement_picks(
        issues, budget=5, min_age_days=2, now=NOW, max_per_cycle=10
    )
    assert len(picks) == 10


def test_zero_budget_disables() -> None:
    issues = [_issue(1, "hydraflow-find", age_days=30)]
    assert retirement_picks(issues, budget=0, min_age_days=2, now=NOW) == []


def test_malformed_created_at_skipped() -> None:
    bad = {
        "number": 9,
        "title": "x",
        "createdAt": "not-a-date",
        "labels": [{"name": "hydraflow-find"}],
    }
    assert retirement_picks([bad], budget=0, min_age_days=0, now=NOW) == []
    assert retirement_picks([bad] * 30, budget=1, min_age_days=0, now=NOW) == []


def test_module_literals_match_config_defaults() -> None:
    """Guard (review MAJOR): the module literal sets must track the config
    defaults so an operator label rename can't silently drop protection —
    the caller sources from config, but the literals are the test-time and
    fallback truth and must not drift."""
    from backlog_budget import ADVISORY_STAGE_LABELS, PROTECTED_LABELS
    from config import HydraFlowConfig

    config = HydraFlowConfig()
    assert (
        frozenset(
            [
                *config.find_label,
                *config.planner_label,
                *config.diagnose_label,
                *config.parked_label,
            ]
        )
        == ADVISORY_STAGE_LABELS
    )
    expected_protected = frozenset(
        [
            *config.ready_label,
            *config.review_label,
            *config.in_progress_label,
            *config.hitl_label,
            *config.hitl_active_label,
            *config.hitl_autofix_label,
            *config.light_autofix_label,
            "human-required",
            "hydraflow-epic",
            "hydraflow-epic-child",
            "hydraflow-refinement-digest",
            "P1",
            "P2",
        ]
    )
    assert expected_protected == PROTECTED_LABELS
