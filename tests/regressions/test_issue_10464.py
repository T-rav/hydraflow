"""Regression #10464: TermProposerLoop drafts must not ship aliases that
already collide with live wiki prose.

#10466 was a hotfix: TermProposerLoop auto-created the CreditExhaustedError
term with prose-phrase aliases ["credit exhaustion", "exhausted billing
signal", "billing-limit signal"]. Two of those are generic English already
used in docs/wiki/dark-factory.md and docs/wiki/gotchas.md to describe the
situation, not paraphrases of the exception class — so
tests/test_seed_terms.py::test_paraphrase_lint_runs_against_live_wiki failed
on staging and blocked every PR's Tests job via the RC promotion gate
(#10462). That PR dropped all three aliases by hand.

This pins the root-cause fix: validate_draft (called from
TermProposerLoop._do_work with wiki_root=terms_root.parent) strips only the
aliases that collide with live wiki prose via strip_wiki_prose_aliases,
so the next auto-proposed term can't reintroduce this failure class — and
non-colliding aliases like "billing-limit signal" still ship.
"""

from __future__ import annotations

from pathlib import Path

from term_proposer_llm import TermDraft
from ubiquitous_language import (
    BoundedContext,
    Candidate,
    TermKind,
    build_symbol_index,
    lint_paraphrases,
    validate_draft,
)

REPO_ROOT = Path(__file__).parent.parent.parent
WIKI_ROOT = REPO_ROOT / "docs" / "wiki"
SRC_ROOT = REPO_ROOT / "src"


def test_validate_draft_strips_aliases_colliding_with_live_wiki_prose() -> None:
    index = build_symbol_index(SRC_ROOT)
    candidate = Candidate(
        name="CreditExhaustedError",
        code_anchor="src/subprocess_util.py:CreditExhaustedError",
        signals=("S2",),
        imports_seen=6,
        importing_term_anchors=(),
    )
    draft = TermDraft(
        include=True,
        definition=(
            "Reproduces the #10466 over-broad alias set to verify "
            "wiki-prose collisions are stripped, not shipped."
        ),
        kind=TermKind.DOMAIN_EVENT,
        bounded_context=BoundedContext.SHARED_KERNEL,
        aliases=[
            "credit exhaustion",
            "exhausted billing signal",
            "billing-limit signal",
        ],
        invariants=[],
        depends_on_anchors=[],
    )

    term, reason = validate_draft(
        candidate,
        draft,
        existing_terms=[],
        symbol_index=index,
        wiki_root=WIKI_ROOT,
    )

    assert reason is None
    assert term is not None
    # "credit exhaustion" (gotchas.md) and "exhausted billing signal"
    # (dark-factory.md) already appear as prose — dropped. "billing-limit
    # signal" appears nowhere in prose — it ships.
    assert term.aliases == ["billing-limit signal"]


def test_stripped_term_passes_paraphrase_lint_against_live_wiki() -> None:
    index = build_symbol_index(SRC_ROOT)
    candidate = Candidate(
        name="CreditExhaustedError",
        code_anchor="src/subprocess_util.py:CreditExhaustedError",
        signals=("S2",),
        imports_seen=6,
        importing_term_anchors=(),
    )
    draft = TermDraft(
        include=True,
        definition=(
            "Reproduces the #10466 over-broad alias set to verify the "
            "resulting term is clean against the live wiki."
        ),
        kind=TermKind.DOMAIN_EVENT,
        bounded_context=BoundedContext.SHARED_KERNEL,
        aliases=[
            "credit exhaustion",
            "exhausted billing signal",
            "billing-limit signal",
        ],
        invariants=[],
        depends_on_anchors=[],
    )

    term, reason = validate_draft(
        candidate,
        draft,
        existing_terms=[],
        symbol_index=index,
        wiki_root=WIKI_ROOT,
    )
    assert reason is None
    assert term is not None

    assert lint_paraphrases([term], WIKI_ROOT) == []
