"""Unit tests for the mutation-gauntlet pure core (#10835).

Pure, fast, no subprocess: ``classify_result`` mapping, ``plan_campaign``
selection, and ``summarize`` kill-rate math (including the ERRORED-excluded
denominator and the empty-campaign no-crash contract).
"""

from __future__ import annotations

from mutation_gauntlet import (
    Mutant,
    MutantClass,
    MutantResult,
    MutantSelector,
    PatchSpec,
    Verdict,
    campaign_row,
    classify_result,
    plan_campaign,
    render_summary,
    summarize,
)


def _mutant(
    mid: str = "m",
    cls: MutantClass = MutantClass.LOGIC,
    gate: str = "unit-tests",
) -> Mutant:
    return Mutant(
        id=mid,
        mutant_class=cls,
        target_gate=gate,
        patch=PatchSpec(file="src/x.py", find="a", replace="b"),
        rationale="fixture mutant",
    )


def _result(
    mutant: Mutant, verdict: Verdict, gate_exit: int | None = 0
) -> MutantResult:
    return MutantResult(mutant=mutant, verdict=verdict, gate_exit=gate_exit)


# -- classify_result ------------------------------------------------------


def test_classify_result_red_gate_is_killed() -> None:
    assert classify_result(1, gate_ran=True) is Verdict.KILLED


def test_classify_result_signal_death_exit_is_killed() -> None:
    assert classify_result(-6, gate_ran=True) is Verdict.KILLED


def test_classify_result_green_gate_is_survived() -> None:
    assert classify_result(0, gate_ran=True) is Verdict.SURVIVED


def test_classify_result_gate_not_run_is_errored() -> None:
    assert classify_result(0, gate_ran=False) is Verdict.ERRORED


def test_classify_result_not_run_is_errored_even_on_red_exit() -> None:
    # A "red" exit code is meaningless when the gate never ran: ERRORED,
    # never KILLED — the fail-closed guard against counting a phantom kill.
    assert classify_result(1, gate_ran=False) is Verdict.ERRORED


# -- plan_campaign / MutantSelector ---------------------------------------


def test_plan_campaign_without_selector_returns_all() -> None:
    catalog = [_mutant("a"), _mutant("b")]
    assert plan_campaign(catalog) == catalog


def test_plan_campaign_filters_by_class() -> None:
    logic = _mutant("l", cls=MutantClass.LOGIC)
    safety = _mutant("s", cls=MutantClass.SAFETY)
    selector = MutantSelector(classes=frozenset({MutantClass.SAFETY}))

    assert plan_campaign([logic, safety], selector) == [safety]


def test_plan_campaign_filters_by_gate() -> None:
    unit = _mutant("u", gate="unit-tests")
    scenario = _mutant("s", gate="scenario")
    selector = MutantSelector(gates=frozenset({"scenario"}))

    assert plan_campaign([unit, scenario], selector) == [scenario]


def test_plan_campaign_filters_by_id() -> None:
    keep = _mutant("keep")
    drop = _mutant("drop")
    selector = MutantSelector(ids=frozenset({"keep"}))

    assert plan_campaign([keep, drop], selector) == [keep]


def test_plan_campaign_selector_is_conjunctive() -> None:
    # id matches but class does not -> excluded (AND, not OR).
    mutant = _mutant("x", cls=MutantClass.LOGIC)
    selector = MutantSelector(
        ids=frozenset({"x"}), classes=frozenset({MutantClass.SAFETY})
    )

    assert plan_campaign([mutant], selector) == []


# -- summarize: kill-rate math --------------------------------------------


def test_summarize_empty_campaign_does_not_crash() -> None:
    report = summarize([])

    assert report.overall.kill_rate is None
    assert report.per_gate == {}
    assert report.per_class == {}


def test_summarize_kill_rate_excludes_errored_from_denominator() -> None:
    mutant = _mutant()
    results = [
        _result(mutant, Verdict.KILLED),
        _result(mutant, Verdict.SURVIVED),
        _result(mutant, Verdict.ERRORED),
    ]

    report = summarize(results)

    # 1 killed / (1 killed + 1 survived) = 0.5; the ERRORED row is not counted.
    assert report.overall.kill_rate == 0.5
    assert report.overall.errored == 1


def test_summarize_all_errored_rate_is_none() -> None:
    mutant = _mutant()

    report = summarize(
        [_result(mutant, Verdict.ERRORED), _result(mutant, Verdict.ERRORED)]
    )

    assert report.overall.kill_rate is None
    assert report.overall.errored == 2


def test_summarize_perfect_campaign_kill_rate_is_one() -> None:
    mutant = _mutant()

    report = summarize(
        [_result(mutant, Verdict.KILLED), _result(mutant, Verdict.KILLED)]
    )

    assert report.overall.kill_rate == 1.0


def test_summarize_per_gate_breakdown() -> None:
    unit = _mutant("u", gate="unit-tests")
    scenario = _mutant("s", gate="scenario")

    report = summarize(
        [_result(unit, Verdict.KILLED), _result(scenario, Verdict.SURVIVED)]
    )

    assert report.per_gate["unit-tests"].kill_rate == 1.0
    assert report.per_gate["scenario"].kill_rate == 0.0


def test_summarize_per_class_breakdown() -> None:
    logic = _mutant("l", cls=MutantClass.LOGIC)
    safety = _mutant("s", cls=MutantClass.SAFETY)

    report = summarize(
        [_result(logic, Verdict.KILLED), _result(safety, Verdict.SURVIVED)]
    )

    assert report.per_class[MutantClass.LOGIC].kill_rate == 1.0
    assert report.per_class[MutantClass.SAFETY].kill_rate == 0.0


def test_summarize_collects_survivors_as_findings() -> None:
    blind = _mutant("blind")

    report = summarize([_result(blind, Verdict.SURVIVED)])

    assert report.has_survivors
    assert report.survivors == (blind,)


def test_summarize_collects_errored_apart_from_survivors() -> None:
    crashy = _mutant("crashy")

    report = summarize([_result(crashy, Verdict.ERRORED)])

    assert report.errored == (crashy,)
    assert not report.has_survivors


# -- campaign_row + render_summary ----------------------------------------


def test_campaign_row_carries_ids_and_findings() -> None:
    blind = _mutant("blind", gate="scenario")
    report = summarize(
        [_result(_mutant("k"), Verdict.KILLED), _result(blind, Verdict.SURVIVED)]
    )

    row = campaign_row(
        report, campaign_id="c1", head_sha="abc123", ts="2026-08-02T00:00:00+00:00"
    )

    assert row["campaign_id"] == "c1"
    assert row["head_sha"] == "abc123"
    assert row["survivors"] == ["blind"]
    assert "kill_rate" in row["overall"]


def test_render_summary_flags_survivors() -> None:
    blind = _mutant("blind-gate")

    text = render_summary(summarize([_result(blind, Verdict.SURVIVED)]))

    assert "SURVIVORS" in text
    assert "blind-gate" in text


def test_render_summary_empty_campaign_reads_na() -> None:
    assert "n/a" in render_summary(summarize([]))


# -- PatchSpec.is_well_formed ---------------------------------------------


def test_patchspec_is_well_formed_for_a_real_change() -> None:
    assert PatchSpec("f", "a", "b").is_well_formed


def test_patchspec_not_well_formed_when_find_equals_replace() -> None:
    assert not PatchSpec("f", "a", "a").is_well_formed


def test_patchspec_not_well_formed_when_find_is_empty() -> None:
    assert not PatchSpec("f", "", "b").is_well_formed
