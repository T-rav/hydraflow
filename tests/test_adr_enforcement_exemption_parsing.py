"""What the ADR-enforcement exemption allow-list will and will not accept.

``EXEMPTION_RE`` had two byte-identical definitions before #11749 — one in the
merge gate, one in the debt report — kept in sync by a comment, and *neither*
had a test for what it refuses. That is the hole this file fills, and it is the
one a consolidation is most likely to make worse: the surviving definition is
now the exemption lane for the ratchet, the report and the decision engine at
once, so widening it widens all three.

Every case below is a way the allow-list could quietly grow. The live
``exemptions.md`` cannot exercise any of them — a widened regex still yields
exactly the three entries it holds today, which is precisely why the property
has to be tested against synthetic text rather than against the repo.
"""

from __future__ import annotations

from adr_conformance import parse_exemptions_text


def test_a_well_formed_entry_parses_with_its_justification() -> None:
    text = "- ADR-0025: no machine-checkable invariant exists for this decision.\n"

    assert parse_exemptions_text(text) == {
        25: "no machine-checkable invariant exists for this decision."
    }


def test_a_bare_id_with_no_justification_is_not_an_exemption() -> None:
    """ "An exemption is a permanent, justified statement" — no reason, no lane."""
    assert parse_exemptions_text("- ADR-0025:\n") == {}


def test_a_whitespace_only_justification_is_not_an_exemption() -> None:
    assert parse_exemptions_text("- ADR-0025:    \n") == {}


def test_an_entry_with_no_colon_is_not_an_exemption() -> None:
    assert parse_exemptions_text("- ADR-0025 no colon here\n") == {}


def test_prose_that_merely_mentions_an_adr_is_not_an_exemption() -> None:
    """The allow-list lives inside a prose standards doc; the doc's own
    explanatory sentences must never become entries."""
    text = (
        "Debt that *can* be enforced belongs in the ratchet baseline, not here.\n"
        "For example ADR-0025: was exempted only after the backfill concluded.\n"
        "See also `ADR-0042: two-tier branches` for a decision that is enforced.\n"
    )

    assert parse_exemptions_text(text) == {}


def test_an_unpadded_id_is_not_an_exemption() -> None:
    """``NNNN`` is zero-padded; ``ADR-25`` is a typo, not a shorter spelling."""
    assert parse_exemptions_text("- ADR-25: typo in the id\n") == {}


def test_an_indented_bullet_is_not_an_exemption() -> None:
    """Entries are top-level bullets in the Active-exemptions list; a nested
    bullet under some other heading must not be picked up."""
    assert parse_exemptions_text("  - ADR-0025: nested under something else\n") == {}


def test_entries_are_read_from_a_document_full_of_prose() -> None:
    """The positive case in context: two real entries among the doc's prose."""
    text = (
        "# ADR-Enforcement Exemptions (allow-list)\n\n"
        "An exemption is **not** a way to defer work. Reach for it only after\n"
        "concluding no real check is feasible.\n\n"
        "## Active exemptions\n\n"
        "- ADR-0025: symmetric field-assertion coverage is a semantic judgment.\n"
        "- ADR-0051: review-until-convergence is a pure human-process cadence.\n"
    )

    assert parse_exemptions_text(text) == {
        25: "symmetric field-assertion coverage is a semantic judgment.",
        51: "review-until-convergence is a pure human-process cadence.",
    }
