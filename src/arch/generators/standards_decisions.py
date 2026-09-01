"""Render every ``(standard, subject)`` verdict the decision seam produces.

Decisions are persisted — `policy.store` appends facts to `facts.jsonl` — and
rendered nowhere. For the v1.1.0 story ("this repo declares its articles; here
is every verdict") that has to be a page, not a JSONL file.

It is also #11687's argument made visible: **the page shows whether the number
is still attached to anything.** A standard the charter declares but nothing
decides renders as a GAP row rather than as absence, because a declared
standard with no verdict and a standard nobody declared look identical in a
table that only lists what it found.

The page renders whatever standards exist. Today that is `adr_enforcement`,
`adr_conformance`, `test_pyramid` and `charter`; siblings make it richer
without changing this generator.

**Pure over its inputs.** It takes decisions and the charter's declared
standards and returns markdown — no engine run, no fact collection, no
filesystem. Deciding is `policy.python_engine`'s job and collecting is
`policy.facts`'; a generator that ran the engine would put a third derivation
in the tree (ADR-0143 Ruling 5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from policy.models import StandardDecision

_HEADER = """# Standards decisions

<!-- GENERATED FILE — do not edit by hand. Regenerate with `make arch-regen`. -->

Every `(standard, subject)` verdict the decision seam (ADR-0143) currently
produces, plus every standard the charter declares that nothing decided.

A **GAP** row is the point of this page: a declared standard with no verdict
and a standard nobody declared look identical in a table that lists only what
it found. `blocking` is orthogonal to `status` — a violation can be reported
without stopping anything, and the two columns say so separately.
"""


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _escape(text: str) -> str:
    """Markdown-table-safe: a pipe in a reason must not split the row."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_standards_decisions(
    decisions: Sequence[StandardDecision],
    *,
    declared_standards: Sequence[str] = (),
) -> str:
    """One table of verdicts, with a GAP row per undecided declared standard."""
    lines = [_HEADER, ""]

    decided = {d.standard for d in decisions}
    gaps = sorted(set(declared_standards) - decided)

    lines.append(
        f"**{len(decisions)}** verdict(s) across **{len(decided)}** standard(s); "
        f"**{len(gaps)}** declared standard(s) with no verdict."
    )
    lines.append("")
    lines.append(_row(["Standard", "Subject", "Status", "Blocking", "Reason"]))
    lines.append(_row(["---", "---", "---", "---", "---"]))

    for decision in sorted(decisions, key=lambda d: (d.standard, str(d.subject))):
        lines.append(
            _row(
                [
                    f"`{decision.standard}`",
                    f"`{decision.subject}`",
                    decision.status.value,
                    "yes" if decision.blocking else "no",
                    _escape(decision.reason or ""),
                ]
            )
        )

    for standard in gaps:
        lines.append(
            _row(
                [
                    f"`{standard}`",
                    "—",
                    "**GAP**",
                    "—",
                    "declared by the charter; no collector emits facts for it, "
                    "so nothing decides it",
                ]
            )
        )

    if not decisions and not gaps:
        lines.append(_row(["—", "—", "—", "—", "no standards declared or decided"]))

    lines.append("")
    return "\n".join(lines)
