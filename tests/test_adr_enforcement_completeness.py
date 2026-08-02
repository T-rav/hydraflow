# tests/test_adr_enforcement_completeness.py
"""Ratchet: every Accepted ADR carries a REAL enforcement check.

Companion to test_prompt_registry_completeness.py, same artifact-class shape one
level up. ``classify_adr_enforcement`` has existed since ADR-0100 and the
classification is published to ``docs/arch/generated/adr-enforcement.md``, but
nothing failed when an ADR landed without a runnable check — measured, not
enforced. ADR-0027 is the evidence it already drifted: it carries no
``**Enforced by:**`` at all and CI stayed green.

REAL means the declared check resolves and is non-mutating. WEAK means a check
is declared but does not resolve (typically a prose review-checklist pointer).
MISSING means no check is declared.

``_PROSE_ONLY`` holds ADRs whose enforcement is genuinely a human convention
rather than a runnable check — these are **declared permanent exceptions, not
debt**. ``_MISSING_ENFORCEMENT`` is debt and SHRINKS ONLY. Both are pinned so a
new ADR cannot be waved through by appending to a set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_conformance import (
    adr_is_unattributed,
    classify_adr_enforcement,
    unattributed_adrs,
)
from adr_index import ADR, Check, parse_adr_file, scan_adr_directory

REPO = Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"

# Enforcement is a human convention by nature: the check names a review step, not
# a command. Declared permanent so they read as decided rather than unfinished.
# Adding to this set is a decision that needs justifying in review, not a shortcut.
_PROSE_ONLY: dict[str, str] = {
    "0025": "symmetric field-assertion coverage — reviewers search the field "
    "name across test functions; no mechanical equivalent proposed",
    "0035": "tests must match the toggle state they assert — a review "
    "checklist item on toggle-gated logic",
    "0051": "iterative production-readiness review — its own text says "
    "'a process convention, not a runnable check'",
}

# ADRs with no enforcement declared at all. This is debt. SHRINKS ONLY.
# Empty since #10867: ADR-0027 (the only entry) was enforced with a resolving
# check rather than exempted — see docs/adr/0027-duplicate-class-merge-artifact-pattern.md.
_MISSING_ENFORCEMENT: dict[str, str] = {}

# Pinned so neither allowlist can grow.
_PROSE_ONLY_MAX = 3
_MISSING_MAX = 0


def _accepted_adrs() -> dict[str, str]:
    """ADR number -> classification, for Accepted ADRs only.

    Accepted-only because ``classify_adr_enforcement`` is defined over that
    population (``src/adr_conformance.py`` skips anything else): Proposed and
    Superseded ADRs are not yet, or no longer, binding.
    """
    out: dict[str, str] = {}
    for path in sorted(ADR_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            adr = parse_adr_file(path)
        except Exception:  # pragma: no cover - a malformed ADR is its own finding
            continue
        if getattr(adr, "status", "") != "Accepted":
            continue
        out[path.name[:4]] = str(classify_adr_enforcement(adr, REPO))
    return out


@pytest.fixture(scope="module")
def classified() -> dict[str, str]:
    return _accepted_adrs()


def test_every_accepted_adr_has_real_enforcement(classified) -> None:
    exempt = set(_PROSE_ONLY) | set(_MISSING_ENFORCEMENT)
    offenders = sorted(
        num
        for num, klass in classified.items()
        if "REAL" not in klass and num not in exempt
    )
    assert not offenders, (
        f"Accepted ADRs without a REAL enforcement check: {offenders}. Add an "
        "`**Enforced by:**` line naming a runnable check (`pytest:` / `make:`) "
        "that resolves and does not mutate. If enforcement is genuinely a human "
        "convention, add it to _PROSE_ONLY with a justification — that is a "
        "decision, not a shortcut."
    )


def test_prose_only_allowlist_does_not_grow() -> None:
    assert len(_PROSE_ONLY) <= _PROSE_ONLY_MAX, (
        f"_PROSE_ONLY grew to {len(_PROSE_ONLY)} (pinned at {_PROSE_ONLY_MAX}). "
        "A new ADR whose enforcement is only a review checklist needs a "
        "recorded decision, not an append."
    )


def test_missing_enforcement_allowlist_only_shrinks() -> None:
    assert len(_MISSING_ENFORCEMENT) <= _MISSING_MAX, (
        f"_MISSING_ENFORCEMENT grew to {len(_MISSING_ENFORCEMENT)} (pinned at "
        f"{_MISSING_MAX}). This allowlist is debt and shrinks only: declare the "
        "ADR's enforcement instead of exempting it."
    )


def test_allowlisted_adrs_still_exist_and_still_need_the_exemption(
    classified,
) -> None:
    """A stale exemption silently widens the gap it was meant to track."""
    stale: list[str] = []
    for num in sorted(set(_PROSE_ONLY) | set(_MISSING_ENFORCEMENT)):
        klass = classified.get(num)
        if klass is None:
            stale.append(f"{num} (not an Accepted ADR any more)")
        elif "REAL" in klass:
            stale.append(f"{num} (now REAL — remove the exemption)")
    assert not stale, (
        f"Allowlist entries that no longer need to be there: {stale}. Remove "
        "them and lower the pinned maximum, so the allowlists reflect real "
        "remaining work."
    )


def test_classification_still_discriminates(classified) -> None:
    """Guards the check itself: if everything classifies REAL, the gate is blind."""
    assert classified, "no Accepted ADRs found — the parser or glob has drifted"
    assert any("REAL" in k for k in classified.values()), (
        "no ADR classified REAL, which means classify_adr_enforcement or the "
        "check resolver has broken rather than the corpus having improved"
    )


# --------------------------------------------------------------------------
# Attribution ratchet (#10861). REAL means "names a runnable check that
# resolves" — it does NOT mean the check relates to the ADR. An Accepted ADR
# whose only `**Enforced by:**` is an unrelated existing test still classifies
# REAL. ``adr_is_unattributed`` is the advisory relatedness signal (does the
# cited test's text name the ADR?); it is deliberately NOT folded into REAL, so
# it moves no ADR's class. Instead it is ratcheted here against a pinned,
# shrink-only baseline: ~46 of today's REAL ADRs cite a test that never names
# them (a naive strict flip would drop them all to WEAK), so the corpus is
# grandfathered as-is and a *new* unattributed ADR fails while the baseline only
# ever shrinks.
# --------------------------------------------------------------------------

# Accepted ADRs that are REAL yet cite only tests that never name them. Measured
# on the live corpus at #10861; pinned so a new offender cannot be waved through
# by appending. SHRINKS ONLY — attribute the cited test (add `ADR-NNNN` to it,
# or repoint the ADR at a test that names it) and drop the entry, never grow it.
_UNATTRIBUTED_BASELINE: frozenset[str] = frozenset(
    {
        "0002", "0004", "0005", "0007", "0008", "0010", "0011", "0012",
        "0014", "0015", "0016", "0017", "0018", "0019", "0022", "0024",
        "0028", "0029", "0032", "0034", "0037", "0041", "0043", "0045",
        "0047", "0050", "0052", "0057", "0058", "0060", "0061", "0064",
        "0071", "0083", "0090", "0093", "0096", "0097", "0102", "0104",
        "0106", "0109", "0110", "0111", "0117", "0119",
    }
)  # fmt: skip
_UNATTRIBUTED_MAX = 46


@pytest.fixture(scope="module")
def accepted_adrs() -> list[ADR]:
    return [a for a in scan_adr_directory(ADR_DIR) if a.status == "Accepted"]


def test_no_unattributed_adr_outside_the_baseline(accepted_adrs) -> None:
    offenders = set(unattributed_adrs(accepted_adrs, REPO))
    new = sorted(offenders - _UNATTRIBUTED_BASELINE)
    assert not new, (
        f"Accepted ADRs whose only enforcement is a test that never names them: "
        f"{new}. REAL only proves the cited test exists, not that it relates to "
        "this ADR. Add the ADR number (e.g. `ADR-0123`) to the enforcing test, "
        "or repoint the ADR at a test that asserts its invariant. Do NOT append "
        "to _UNATTRIBUTED_BASELINE — it shrinks only."
    )


def test_unattributed_baseline_only_shrinks() -> None:
    assert len(_UNATTRIBUTED_BASELINE) <= _UNATTRIBUTED_MAX, (
        f"_UNATTRIBUTED_BASELINE grew to {len(_UNATTRIBUTED_BASELINE)} (pinned at "
        f"{_UNATTRIBUTED_MAX}). This baseline is debt and shrinks only: attribute "
        "the cited test instead of grandfathering another ADR."
    )


def test_unattributed_baseline_has_no_stale_entries(accepted_adrs) -> None:
    """A baseline entry that is now attributed (or no longer an Accepted REAL
    ADR) silently reserves headroom for un-attribution. Drop it and lower the
    max so the baseline reflects real remaining debt."""
    still_unattributed = set(unattributed_adrs(accepted_adrs, REPO))
    stale = sorted(_UNATTRIBUTED_BASELINE - still_unattributed)
    assert not stale, (
        f"_UNATTRIBUTED_BASELINE entries that are no longer unattributed: {stale}. "
        "The cited test now names the ADR (or the ADR is no longer Accepted/REAL). "
        f"Remove them and lower _UNATTRIBUTED_MAX from {_UNATTRIBUTED_MAX}."
    )


def test_a_new_adr_citing_an_unrelated_file_is_flagged() -> None:
    """The gap #10861 closes: a fresh Accepted ADR pointing its only check at a
    real-but-unrelated test resolves (so it is REAL) yet is caught as
    unattributed, so it cannot land silently outside the baseline."""
    synthetic = ADR(
        number=9999,
        title="synthetic — unrelated enforcement",
        status="Accepted",
        summary="",
        enforcement="enforced",
        enforced_by=(
            Check(
                kind="pytest",
                target="tests/test_prompt_fitness.py",
                raw="pytest:tests/test_prompt_fitness.py",
            ),
        ),
    )
    assert adr_is_unattributed(synthetic, REPO)
    assert "9999" not in _UNATTRIBUTED_BASELINE
    assert set(unattributed_adrs([synthetic], REPO)) == {"9999"}
