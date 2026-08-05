"""Unit tests for the ADR checkable-assertion density engine (#10917)."""

from __future__ import annotations

from typing import Literal

from adr_assertion_density import (
    EXECUTABLE_KINDS,
    check_is_executable,
    density_for_adr,
    population_density,
)
from adr_index import ADR, Check
from arch.generators.adr_assertion_density_report import render_adr_assertion_density

_Kind = Literal["pytest", "make", "script", "prose"]


def _check(kind: _Kind, target: str = "x") -> Check:
    return Check(kind=kind, target=target, raw=f"{kind}:{target}")


def _adr(number: int, status: str, *checks: Check, title: str = "t") -> ADR:
    return ADR(
        number=number,
        title=title,
        status=status,
        summary="s",
        enforced_by=tuple(checks),
    )


def test_check_is_executable_covers_the_three_runnable_kinds() -> None:
    assert sorted(EXECUTABLE_KINDS) == ["make", "pytest", "script"]
    assert check_is_executable(_check("pytest"))
    assert check_is_executable(_check("make"))
    assert check_is_executable(_check("script"))
    assert not check_is_executable(_check("prose"))


def test_density_is_the_executable_share_of_cited_checks() -> None:
    adr = _adr(1, "Accepted", _check("pytest"), _check("pytest"), _check("prose"))
    d = density_for_adr(adr)
    assert d.total_checks == 3
    assert d.executable_checks == 2
    assert d.prose_checks == 1
    assert d.density == 2 / 3
    assert d.kind_counts == {"pytest": 2, "make": 0, "script": 0, "prose": 1}


def test_all_prose_adr_is_zero_density_and_all_executable_is_one() -> None:
    assert density_for_adr(_adr(1, "Accepted", _check("prose"))).density == 0.0
    assert density_for_adr(_adr(2, "Accepted", _check("make"))).density == 1.0


def test_adr_with_no_checks_is_zero_density_not_undefined() -> None:
    d = density_for_adr(_adr(1, "Accepted"))
    assert d.total_checks == 0
    assert d.density == 0.0  # an unenforced decision reads as zero, never 1/0


def test_population_filters_to_the_requested_statuses() -> None:
    adrs = [
        _adr(1, "Accepted", _check("pytest")),
        _adr(2, "Proposed", _check("pytest")),
        _adr(3, "Superseded", _check("pytest")),
    ]
    pop = population_density(adrs)  # default: Accepted only
    assert pop.n_adrs == 1
    assert [d.number for d in pop.per_adr] == [1]
    # Explicit multi-status selection widens it.
    assert population_density(adrs, statuses=("Accepted", "Proposed")).n_adrs == 2


def test_mean_density_and_executable_fraction_are_distinct_measures() -> None:
    # One all-executable ADR (1 check) + one diluted ADR (1 exec, 3 prose).
    adrs = [
        _adr(1, "Accepted", _check("pytest")),
        _adr(
            2,
            "Accepted",
            _check("pytest"),
            _check("prose"),
            _check("prose"),
            _check("prose"),
        ),
    ]
    pop = population_density(adrs)
    # Per-ADR mean: (1.0 + 0.25) / 2 = 0.625 — each ADR counts once.
    assert pop.mean_density == 0.625
    # Check-weighted: 2 executable of 5 total = 0.4 — the verbose ADR dominates.
    assert pop.executable_fraction == 0.4
    assert pop.kind_totals == {"pytest": 2, "make": 0, "script": 0, "prose": 3}


def test_prose_outliers_flag_adrs_above_the_shewhart_limit() -> None:
    # A corpus that is almost all executable, with one prose-heavy outlier.
    adrs = [_adr(n, "Accepted", _check("pytest")) for n in range(1, 10)]
    adrs.append(_adr(99, "Accepted", *[_check("prose") for _ in range(5)]))
    pop = population_density(adrs)
    assert pop.prose_ucl >= 0.0
    assert 99 in pop.prose_outliers
    assert all(n != 1 for n in pop.prose_outliers)  # the executable ADRs are clean


def test_empty_population_is_calm_zeroes_not_a_crash() -> None:
    pop = population_density([])
    assert pop.n_adrs == 0
    assert pop.mean_density == 0.0
    assert pop.executable_fraction == 0.0
    assert pop.prose_outliers == ()


def test_generator_renders_headline_and_footer_sentinel() -> None:
    adrs = [
        _adr(1, "Accepted", _check("pytest"), title="Real ADR"),
        _adr(2, "Accepted", _check("prose"), title="Prose ADR"),
    ]
    out = render_adr_assertion_density(adrs)
    assert "# ADR Checkable-Assertion Density" in out
    assert "Accepted (2 ADRs)" in out
    assert "ADR-0001" in out and "ADR-0002" in out
    assert out.rstrip().endswith("{{ARCH_FOOTER}}")  # runner substitutes the sentinel


def test_generator_empty_population_message() -> None:
    out = render_adr_assertion_density([])
    assert "no ADRs in the Accepted population" in out
