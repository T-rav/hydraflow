"""Regression pins: the rung-0 instrument must not measure itself (#11055).

Live run against 19,087 real events exposed two miswirings and one
dangerous conclusion:

1. The runner filtered work evidence through an ALLOW-list of event types
   (`phase_change`/`worker_update`/`pr_created`) that this factory does
   not emit, while its own docstring promised "any worker/phase/PR event
   naming the issue".
2. It read the event body from `payload`; the bus writes `data`.

Together those produced ZERO classified issues against a full log — and
the report printed "INSUFFICIENT EVIDENCE", which reads as *the factory
is young* rather than *the instrument is blind*.

3. With the wiring fixed, all 37 classified issues came back `build` and
   the report declared "FIXED DAG VINDICATED" — while every non-build rule
   keyed off a signal the exhaust does not yet carry. A 0% rate there
   measures the exhaust, not the pipeline; closing a 12-month roadmap on
   it would be closing on a tautology.
"""

from __future__ import annotations

from mode_mismatch import (
    IssueTrace,
    MismatchReport,
    Mode,
    decision,
    discriminating,
)


def _worked(**kwargs) -> IssueTrace:
    base = {"issue_number": 1, "merged": True, "work_started": True}
    return IssueTrace(**{**base, **kwargs})


def test_population_with_no_non_build_signal_is_not_discriminating() -> None:
    traces = [_worked(issue_number=n) for n in range(1, 40)]
    assert discriminating(traces) is False


def test_any_non_build_signal_makes_it_discriminating() -> None:
    for kwargs in (
        {"route_backs": 1},
        {"hitl_escalations": 1},
        {"gave_up": True, "merged": False},
        {"decomposed_after_attempt": True},
        {"closed_unmerged": True, "merged": False},
    ):
        assert discriminating([_worked(**kwargs)]) is True, kwargs


def test_signals_on_unclassified_traces_do_not_count() -> None:
    """A signal on a trace that never reaches classify() (never worked, or
    not terminal) cannot produce a non-build verdict — counting it would
    re-open the tautology."""
    never_worked = IssueTrace(
        issue_number=2, closed_unmerged=True, work_started=False, hitl_escalations=3
    )
    not_terminal = IssueTrace(issue_number=3, work_started=True, route_backs=5)
    assert discriminating([never_worked, not_terminal]) is False


def test_non_discriminating_run_refuses_both_verdicts() -> None:
    """The load-bearing guard: neither 'vindicated' nor 'proceed' may be
    read from a run that could only ever have said build."""
    report = MismatchReport(total=37, wrong=0, by_mode={Mode.BUILD: 37})
    sentence = decision(report, discriminating_signals=False)
    assert "NOT DISCRIMINATING" in sentence
    assert "VINDICATED" not in sentence
    assert "PROCEED" not in sentence


def test_discriminating_run_still_reaches_a_real_verdict() -> None:
    """With signals present the gate is transparent — the rate decides."""
    vindicated = decision(
        MismatchReport(total=40, wrong=1, by_mode={Mode.BUILD: 39, Mode.PROBE: 1}),
        discriminating_signals=True,
    )
    assert "VINDICATED" in vindicated
    proceed = decision(
        MismatchReport(total=40, wrong=12, by_mode={Mode.BUILD: 28, Mode.PROBE: 12}),
        discriminating_signals=True,
    )
    assert "PROCEED TO RUNG 1" in proceed
