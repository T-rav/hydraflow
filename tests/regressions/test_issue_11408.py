"""Regression: retirement_picks() null-vs-empty asymmetry between its two
label-set overrides (#11408 — sampled re-audit of #11390).

``protected_labels`` distinguishes "caller passed nothing" (``None`` ->
module literals) from "caller passed an explicit empty set" (honoured
as-is) via ``protected_labels if protected_labels is not None else
PROTECTED_LABELS``. ``advisory_labels`` used a truthy ``or`` instead
(``advisory_labels or ADVISORY_STAGE_LABELS``), which treats an
explicitly-empty frozenset the same as ``None`` and silently falls back
to the hardcoded module literals — reviving, on the advisory side,
exactly the config-drift risk #11390's own review commit fixed on the
protected side.

Both parameters must agree on what "empty" means: ``None``/omitted ->
module literals; explicit empty set -> honoured as-is (empty advisory
means zero candidates; empty protected means nothing is protected).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backlog_budget import ADVISORY_STAGE_LABELS, PROTECTED_LABELS, retirement_picks

NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)


def _issue(number: int, *labels: str, age_days: float = 30.0) -> dict:
    created = NOW - timedelta(days=age_days)
    return {
        "number": number,
        "title": f"issue {number}",
        "createdAt": created.isoformat().replace("+00:00", "Z"),
        "labels": [{"name": name} for name in labels],
    }


def test_explicit_empty_advisory_labels_retires_nothing() -> None:
    """The bug: an explicit empty advisory set must retire nothing, even
    when the board is over budget and every issue carries hydraflow-find."""
    issues = [_issue(i, "hydraflow-find") for i in range(1, 6)]
    picks = retirement_picks(
        issues,
        budget=1,
        min_age_days=0,
        now=NOW,
        advisory_labels=frozenset(),
    )
    assert picks == []


def test_the_two_parameters_agree_on_what_empty_means() -> None:
    """Empty protected drops all protection; empty advisory yields zero
    candidates — the two overrides must treat 'explicit empty' the same way."""
    protected_target = _issue(1, "hydraflow-find", "human-required", age_days=30)
    protected_filler = _issue(2, "hydraflow-find", age_days=5)

    # Empty protected_labels: nothing is protected, so the human-required
    # issue is a candidate again; being oldest and over budget, it's picked.
    protected_empty = retirement_picks(
        [protected_target, protected_filler],
        budget=1,
        min_age_days=0,
        now=NOW,
        protected_labels=frozenset(),
    )
    assert [p.number for p in protected_empty] == [1]

    advisory_a = _issue(3, "hydraflow-find", age_days=30)
    advisory_b = _issue(4, "hydraflow-find", age_days=20)

    # Empty advisory_labels: no label class is advisory, so neither issue
    # is ever a candidate — even though there are 2 of them and budget=1
    # would otherwise produce an overage of 1.
    advisory_empty = retirement_picks(
        [advisory_a, advisory_b],
        budget=1,
        min_age_days=0,
        now=NOW,
        advisory_labels=frozenset(),
    )
    assert advisory_empty == []


def test_omitted_advisory_labels_falls_back_to_module_literals() -> None:
    """Counter-pin: rejects a fix that deletes the None -> literals fallback."""
    issues = [
        _issue(1, "hydraflow-find", age_days=30),
        _issue(2, "hydraflow-find", age_days=20),
        _issue(3, "hydraflow-find", age_days=10),
    ]
    picks = retirement_picks(issues, budget=2, min_age_days=0, now=NOW)
    assert [p.number for p in picks] == [1]


def test_omitted_protected_labels_falls_back_to_module_literals() -> None:
    """Counter-pin: rejects a fix that deletes the None -> literals fallback."""
    issues = [
        _issue(1, "hydraflow-find", "human-required", age_days=30),
        _issue(2, "hydraflow-find", age_days=5),
    ]
    picks = retirement_picks(issues, budget=1, min_age_days=0, now=NOW)
    assert picks == []


def test_renamed_advisory_scheme_honoured_old_labels_not_candidates() -> None:
    """Counter-pin: rejects a fix that hardcodes literals unconditionally
    instead of sourcing from the caller's config."""
    renamed = frozenset({"custom-find"})
    issues = [
        _issue(1, "hydraflow-find", age_days=30),  # old hardcoded literal only
        _issue(2, "custom-find", age_days=30),  # new operator scheme, oldest
        _issue(3, "custom-find", age_days=5),  # new operator scheme, newer
    ]
    picks = retirement_picks(
        issues,
        budget=1,
        min_age_days=0,
        now=NOW,
        advisory_labels=renamed,
    )
    assert [p.number for p in picks] == [2]


def test_explicit_empty_protected_set_already_honoured() -> None:
    """Counter-pin: this direction already worked before the fix and must
    stay working."""
    issues = [
        _issue(1, "hydraflow-find", "P1", age_days=30),
        _issue(2, "hydraflow-find", age_days=5),
    ]
    picks = retirement_picks(
        issues,
        budget=1,
        min_age_days=0,
        now=NOW,
        protected_labels=frozenset(),
    )
    assert [p.number for p in picks] == [1]


def test_config_guard_is_the_only_thing_blocking_the_live_path() -> None:
    """Scope tripwire: HydraFlowConfig rejects empty advisory-label config
    fields today, so the live call site in stale_issue_loop.py can never
    actually pass an empty advisory_labels frozenset. This test documents
    that invariant so it fires (goes red) if the guard is ever relaxed —
    at which point the retirement_picks() fix in this issue is what keeps
    the fail-safe direction (retire nothing) correct."""
    import pytest
    from pydantic import ValidationError

    from config import HydraFlowConfig

    with pytest.raises(ValidationError):
        HydraFlowConfig(find_label=[])
    with pytest.raises(ValidationError):
        HydraFlowConfig(planner_label=[])
    with pytest.raises(ValidationError):
        HydraFlowConfig(diagnose_label=[])
    with pytest.raises(ValidationError):
        HydraFlowConfig(parked_label=[])

    # Sanity: the module literals used as the None-fallback still match
    # what an unconfigured operator would get.
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
    assert PROTECTED_LABELS  # sanity: non-empty module default
