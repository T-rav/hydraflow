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

from adr_conformance import classify_adr_enforcement
from adr_index import parse_adr_file

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
