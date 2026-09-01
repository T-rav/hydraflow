"""The verdicts page (#11868).

Decisions were persisted and rendered nowhere. For the v1.1.0 story — "this
repo declares its articles; here is every verdict" — that has to be a page.

It is also #11687's argument made visible: the page shows whether the number is
still attached to anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from arch.generators.standards_decisions import render_standards_decisions
from policy.models import DecisionStatus, StandardDecision


def _decision(
    standard: str = "adr_enforcement",
    subject: str = "ADR-0100",
    status: DecisionStatus = DecisionStatus.COMPLIANT,
    *,
    blocking: bool = False,
    reason: str = "ok",
) -> StandardDecision:
    return StandardDecision(
        standard=standard,
        subject=subject,
        status=status,
        blocking=blocking,
        reason=reason,
    )


class TestTheGapRow:
    """The reason this page exists rather than a `grep` over facts.jsonl."""

    def test_a_declared_standard_with_no_verdict_renders_as_a_gap(self) -> None:
        """A declared standard with no verdict and a standard nobody declared
        look identical in a table that lists only what it found."""
        page = render_standards_decisions(
            [_decision()], declared_standards=("adr_enforcement", "testing")
        )

        assert "**GAP**" in page
        assert "`testing`" in page
        assert "no collector emits facts for it" in page

    def test_a_decided_standard_is_not_a_gap(self) -> None:
        """Anti-vacuity: every declared standard rendering as a GAP would
        satisfy the test above while saying nothing."""
        page = render_standards_decisions(
            [_decision()], declared_standards=("adr_enforcement",)
        )
        # The header PROSE explains what a GAP row is, so scanning the whole
        # page finds it either way. Only the table body answers the question.
        rows = [ln for ln in page.splitlines() if ln.startswith("| `")]
        assert not any("**GAP**" in row for row in rows)

    def test_the_counts_separate_verdicts_from_gaps(self) -> None:
        page = render_standards_decisions(
            [_decision(), _decision(subject="ADR-0101")],
            declared_standards=("adr_enforcement", "testing", "ports-and-loops"),
        )
        assert "**2** verdict(s)" in page
        assert "**2** declared standard(s) with no verdict" in page


class TestTheTable:
    def test_blocking_is_its_own_column(self) -> None:
        """`blocking` is orthogonal to `status` (ADR-0143 amendment): a
        violation can be reported without stopping anything, and folding them
        into one column would make a non-blocking violation unreadable."""
        page = render_standards_decisions(
            [
                _decision(
                    status=DecisionStatus.VIOLATED, blocking=False, reason="advisory"
                ),
                _decision(
                    subject="ADR-0101",
                    status=DecisionStatus.VIOLATED,
                    blocking=True,
                    reason="hard stop",
                ),
            ]
        )
        assert "| violated | no |" in page
        assert "| violated | yes |" in page

    def test_a_pipe_in_a_reason_does_not_split_the_row(self) -> None:
        """Reasons are engine-authored prose and one already contains a pipe
        (`work | factory | both`). An unescaped one silently adds a column and
        the table stops rendering."""
        page = render_standards_decisions(
            [_decision(reason="binds is work | factory | both")]
        )
        row = next(ln for ln in page.splitlines() if "binds is" in ln)
        # Count UNESCAPED pipes: `\|` is the escape and must not be counted as
        # a column separator, which is the whole point of escaping it.
        unescaped = row.replace("\\|", "")
        assert unescaped.count("|") == 6, f"the reason split the row: {row!r}"
        assert "\\|" in row, "the pipe was not escaped at all"

    def test_a_newline_in_a_reason_does_not_split_the_row(self) -> None:
        page = render_standards_decisions([_decision(reason="line one\nline two")])
        assert "line one line two" in page

    def test_rows_are_sorted_so_regeneration_is_idempotent(self) -> None:
        """An unstable order makes every regen a diff, and the staleness gate
        then fails for reasons unrelated to any change."""
        decisions = [
            _decision(subject="ADR-0200"),
            _decision(subject="ADR-0100"),
            _decision(standard="adr_conformance", subject="ADR-0150"),
        ]
        first = render_standards_decisions(decisions)
        second = render_standards_decisions(list(reversed(decisions)))
        assert first == second


class TestTheEmptyCase:
    def test_a_repo_with_nothing_declared_or_decided_says_so(self) -> None:
        """A table with a header and no rows reads as broken rendering."""
        page = render_standards_decisions([])
        assert "no standards declared or decided" in page


class TestTheCommittedArtifact:
    """The page is a committed artifact under the staleness gate."""

    def test_it_exists_and_carries_real_verdicts(self) -> None:
        """Not only GAP rows.

        The generator collects from the TREE rather than the fact ledger: the
        ledger is gitignored runtime state, so reading it would make this
        artifact depend on whether someone had run the factory, and the
        staleness gate would then fail for everyone else.
        """
        page = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "arch"
            / "generated"
            / "standards-decisions.md"
        ).read_text("utf-8")

        assert "| `adr_enforcement` |" in page
        assert "compliant" in page or "grandfathered" in page
        assert "verdict(s) across" in page

    def test_it_is_marked_generated(self) -> None:
        page = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "arch"
            / "generated"
            / "standards-decisions.md"
        ).read_text("utf-8")
        assert "GENERATED FILE" in page


@pytest.mark.parametrize(
    "status",
    list(DecisionStatus),
    ids=[s.name for s in DecisionStatus],
)
def test_every_status_renders(status: DecisionStatus) -> None:
    """Parametrised over the enum by reference, so a fifth status added later
    arrives here already covered rather than rendering blank."""
    page = render_standards_decisions([_decision(status=status)])
    assert status.value in page
