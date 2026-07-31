"""Verifies seed terms parse, anchors resolve, contexts/kinds are valid."""

from __future__ import annotations

from pathlib import Path

import pytest

from ubiquitous_language import (
    BoundedContext,
    Term,
    TermKind,
    TermStore,
    build_symbol_index,
    lint_overbroad_aliases,
    lint_paraphrases,
    resolve_anchor,
)

REPO_ROOT = Path(__file__).parent.parent
TERMS_DIR = REPO_ROOT / "docs" / "wiki" / "terms"
SRC_DIR = REPO_ROOT / "src"

EXPECTED_NAMES = {
    "HydraFlowConfig",
    "EventBus",
    "StateTracker",
    "BaseBackgroundLoop",
    "RepoWikiStore",
    "PRPort",
    "WorkspacePort",
    "IssueStorePort",
    "AgentRunner",
    "DisturbanceDampenerLoop",
    "ViolationDetector",
    "DimensionBaseline",
    # Control-theory role terms (ADR-0099)
    "Plant",
    "Sensor",
    "Set-point",
    "Error",
    "Controller",
    "Actuator",
    "Governor",
}


@pytest.fixture(scope="module")
def seed_terms() -> list[Term]:
    return TermStore(TERMS_DIR).list()


def test_all_expected_seed_terms_present(seed_terms: list[Term]) -> None:
    actual = {t.name for t in seed_terms}
    missing = EXPECTED_NAMES - actual
    assert not missing, f"Missing seed terms: {missing}"


def test_all_seed_anchors_resolve(seed_terms: list[Term]) -> None:
    index = build_symbol_index(SRC_DIR)
    unresolved = [
        (t.name, t.code_anchor)
        for t in seed_terms
        if not resolve_anchor(t.code_anchor, index)
    ]
    assert not unresolved, f"Unresolved anchors: {unresolved}"


def test_seed_terms_use_valid_kinds_and_contexts(seed_terms: list[Term]) -> None:
    for t in seed_terms:
        assert isinstance(t.kind, TermKind)
        assert isinstance(t.bounded_context, BoundedContext)


def test_seed_terms_have_definitions_and_anchors(seed_terms: list[Term]) -> None:
    for t in seed_terms:
        assert len(t.definition) >= 30, f"{t.name}: definition too short"
        assert ":" in t.code_anchor, f"{t.name}: malformed anchor"


def test_seed_terms_are_accepted(seed_terms: list[Term]) -> None:
    """All term files ship as `accepted`. Auto-grown terms from
    `TermProposerLoop` (ADR-0054) ship `accepted` directly — the LLM-inclusion
    judgment + F1 validation is the gate; no soft-launch lifecycle. Provenance
    fields (`proposed_by` etc.) still mark origin for audits."""
    for t in seed_terms:
        assert t.confidence == "accepted", f"{t.name} should ship as accepted"


def test_paraphrase_lint_runs_against_live_wiki() -> None:
    terms = TermStore(TERMS_DIR).list()
    violations = lint_paraphrases(terms, REPO_ROOT / "docs" / "wiki")
    assert violations == []


def test_no_overbroad_aliases_in_live_wiki() -> None:
    """An alias must be a paraphrase, not a common English word.

    ``TermProposerLoop`` proposed ``"event"`` as an alias for
    ``HydraFlowEvent`` (#10919). The paraphrase lint then flagged 7
    pre-existing uses and ``make quality`` went red on staging for everyone —
    on a test unrelated to whatever they were working on (#10926).

    This is the *earlier* question: not "is this page using a paraphrase" but
    "is this alias too broad to be one". It fails at proposal time, where the
    fix is cheap, rather than in the next person's build.
    """
    terms = TermStore(TERMS_DIR).list()
    violations = lint_overbroad_aliases(terms, REPO_ROOT / "docs" / "wiki")
    assert violations == [], "\n".join(
        ["Aliases too broad to canonicalise:", *(f"  - {v}" for v in violations)]
    )


def test_overbroad_guard_catches_the_alias_that_broke_the_build() -> None:
    """Guards the guard: a detector that stops detecting is worse than none.

    Pinned to the exact 2026-07-31 defect — ``"event"``, which appears as
    ordinary prose in 7 wiki files.
    """
    terms = TermStore(TERMS_DIR).list()
    target = next(t for t in terms if t.name == "HydraFlowEvent")
    poisoned = [target.model_copy(update={"aliases": [*target.aliases, "event"]})]
    violations = lint_overbroad_aliases(poisoned, REPO_ROOT / "docs" / "wiki")
    assert violations, "the over-broad guard no longer detects the bare word 'event'"
    assert "'event'" in violations[0]
