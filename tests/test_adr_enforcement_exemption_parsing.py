"""What the ADR-enforcement exemption allow-list will and will not accept.

``EXEMPTION_RE`` had two byte-identical definitions before #11749 — one in the
merge gate, one in the debt report — kept in sync by a comment, and *neither*
had a test for what it refuses. That is the hole this file fills, and it is the
one a consolidation is most likely to make worse: the surviving definition is
now the exemption lane for the ratchet, the report and the decision engine at
once, so widening it widens all three.

Every refused shape below is a way the allow-list could quietly grow. The live
``exemptions.md`` cannot exercise any of them — a widened regex still yields
exactly the three entries it holds today, which is why the property has to be
tested against synthetic text rather than against the repo. The two accepting
tests are what stop the refusal table from passing over a parser that returns
``{}`` for everything.
"""

from __future__ import annotations

import pytest

from adr_conformance import parse_exemptions_text

#: ``(case_id, text, why_it_must_be_refused)``. The reason travels with the
#: case because it is the load-bearing half: "this string does not parse" is a
#: fact about the regex, and "an exemption without a justification is not an
#: exemption" is the rule that fact is evidence for.
_REFUSED: tuple[tuple[str, str, str], ...] = (
    (
        "bare_id_no_justification",
        "- ADR-0025:\n",
        "an exemption is a permanent, justified statement — no reason, no lane",
    ),
    (
        "whitespace_only_justification",
        "- ADR-0025:    \n",
        "blank is not a justification, however it is spelled",
    ),
    (
        "no_colon",
        "- ADR-0025 no colon here\n",
        "the entry shape is `- ADR-NNNN: <reason>`; a bullet alone is prose",
    ),
    (
        "unpadded_id",
        "- ADR-25: typo in the id\n",
        "`NNNN` is zero-padded; `ADR-25` is a typo, not a shorter spelling",
    ),
    (
        "indented_bullet",
        "  - ADR-0025: nested under something else\n",
        "entries are top-level bullets in the Active-exemptions list",
    ),
    (
        "prose_mention",
        "For example ADR-0025: was exempted after the backfill concluded.\n"
        "See also `ADR-0042: two-tier branches` for an enforced decision.\n",
        "the allow-list lives inside a prose doc; its own sentences are not entries",
    ),
)


@pytest.mark.parametrize(
    ("text", "reason"),
    [pytest.param(text, reason, id=case_id) for case_id, text, reason in _REFUSED],
)
def test_the_allow_list_refuses_shapes_that_would_widen_it(
    text: str, reason: str
) -> None:
    assert parse_exemptions_text(text) == {}, (
        f"the exemption regex accepted {text!r}, widening the allow-list for the "
        f"ratchet, the debt report and the decision engine at once — {reason}"
    )


def test_a_well_formed_entry_parses_with_its_justification() -> None:
    text = "- ADR-0025: no machine-checkable invariant exists for this decision.\n"

    assert parse_exemptions_text(text) == {
        25: "no machine-checkable invariant exists for this decision."
    }


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
