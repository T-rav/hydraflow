"""Parse the ADR lineage fields (ADR-0113): ``Precedent:`` and ``Divergence:``.

Pure functions over ADR text — no I/O beyond reading files handed in by path,
no mutation. The audit's P1.17 CULTURAL check (``checks/p1_docs.py``) uses
these to warn when a *control-plane* ADR carries neither line, and to flag any
``Divergence:`` that cites no receipt.

The two fields, per ADR-0113 (which extends the ADR-0044 audit contract):

* ``Precedent: <tradition> (<canonical source>)`` — the named engineering
  tradition a decision inherits. Optional; must be a real, citable tradition.
* ``Divergence: <assumption>, <forcing condition>, <rule>`` — the assumption in
  that tradition that breaks here, citing the *receipt* (an ADR, incident, or
  audit finding) that forced it. A ``Divergence:`` without a receipt token is a
  violation: unforced invention is a defect, forced invention has a receipt.

Both are parsed tolerantly across the bold-inline (``**Precedent:** ...``) and
plain (``Precedent: ...``) header-field forms ADRs use — ``**`` markers are
stripped before matching so the two forms parse identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# The control-plane ADRs — the decisions that define the control system — per
# the lineage-pass proposal (docs/proposals/lineage-pass-precedent-divergence.md)
# and ADR-0113. These records must let a reviewer tell inherited engineering
# from genuine novelty, so each should carry a Precedent: or Divergence: line.
# The "vitals" and "judge-independence" records named in the proposal have no
# standalone ADR file in the corpus yet, so they are not enumerated here; the
# seed pass (#10674 child 3) revises this set as it lands lines. ADR-0114
# (per-type EventBus subscription, #10660) defines the event fan-out contract
# loops route on, so it joins the set with its own Precedent/Divergence lines.
CONTROL_PLANE_ADRS: frozenset[int] = frozenset(
    {2, 29, 44, 49, 51, 94, 95, 96, 97, 98, 99, 100, 101, 103, 104, 114}
)

# A lineage field line. ``**`` bold markers are stripped before matching, so
# both ``**Precedent:** X`` and ``Precedent: X`` reach these. Anchored at line
# start so a prose or bulleted mention (``- `Precedent:` names ...``) is never
# mistaken for the field itself.
_PRECEDENT_RE = re.compile(r"^Precedent:\s*(.+?)\s*$")
_DIVERGENCE_RE = re.compile(r"^Divergence:\s*(.+?)\s*$")

# A receipt token: the ADR / incident / audit finding that forced a divergence.
# One of an issue/PR reference (``#1234``), an ADR reference (``ADR-0099``), the
# words ``incident`` / ``audit finding``, or a ``docs/`` record path (a
# proposal or incident write-up). Matching any one satisfies "cite the receipt".
_RECEIPT_RE = re.compile(
    r"#\d+|ADR-\d{3,4}|\bincident\b|\baudit finding\b|docs/[\w./-]+",
    re.IGNORECASE,
)

# ``0113-adr-lineage-....md`` → 113.
_ADR_FILE_RE = re.compile(r"^(\d{4})-")


@dataclass(frozen=True)
class LineageFields:
    """The two optional lineage fields parsed from one ADR's text."""

    precedent: str | None
    divergence: str | None

    @property
    def has_any(self) -> bool:
        return self.precedent is not None or self.divergence is not None

    @property
    def divergence_has_receipt(self) -> bool:
        """True when a Divergence: line is present AND cites a receipt token."""
        return self.divergence is not None and bool(_RECEIPT_RE.search(self.divergence))


def _strip_markers(raw: str) -> str:
    """Drop bold markers and surrounding whitespace so both field forms match."""
    return raw.replace("**", "").strip()


def parse_lineage(text: str) -> LineageFields:
    """Extract the first ``Precedent:`` and ``Divergence:`` lines from ADR text."""
    precedent: str | None = None
    divergence: str | None = None
    for raw in text.splitlines():
        line = _strip_markers(raw)
        if precedent is None:
            match = _PRECEDENT_RE.match(line)
            if match:
                precedent = match.group(1).strip()
                continue
        if divergence is None:
            match = _DIVERGENCE_RE.match(line)
            if match:
                divergence = match.group(1).strip()
        if precedent is not None and divergence is not None:
            break
    return LineageFields(precedent=precedent, divergence=divergence)


def adr_number_from_filename(path: Path) -> int | None:
    """Return the four-digit ADR number encoded in a filename, or None."""
    match = _ADR_FILE_RE.match(path.name)
    return int(match.group(1)) if match else None


def extract_lineage_table(adr_dir: Path) -> dict[int, LineageFields]:
    """Map every ADR number in *adr_dir* to its parsed lineage fields.

    This is the "extract a lineage table from the corpus" capability the
    proposal calls for: a reviewer (or a generated doc) can read inherited vs
    novel straight off the returned table.
    """
    table: dict[int, LineageFields] = {}
    for adr in sorted(adr_dir.glob("*.md")):
        number = adr_number_from_filename(adr)
        if number is None:
            continue
        table[number] = parse_lineage(adr.read_text(encoding="utf-8", errors="replace"))
    return table


@dataclass(frozen=True)
class LineageGaps:
    """What the P1.17 check warns on."""

    # Control-plane ADRs present on disk carrying neither lineage line.
    control_plane_missing_both: list[int]
    # ADRs (any, not only control-plane) whose Divergence: line cites no receipt.
    divergence_without_receipt: list[int]

    @property
    def clean(self) -> bool:
        return not (self.control_plane_missing_both or self.divergence_without_receipt)


def find_lineage_gaps(adr_dir: Path) -> LineageGaps:
    """Compute the control-plane coverage gap and the receipt-less divergences."""
    table = extract_lineage_table(adr_dir)
    missing_both = sorted(
        number
        for number, fields in table.items()
        if number in CONTROL_PLANE_ADRS and not fields.has_any
    )
    no_receipt = sorted(
        number
        for number, fields in table.items()
        if fields.divergence is not None and not fields.divergence_has_receipt
    )
    return LineageGaps(
        control_plane_missing_both=missing_both,
        divergence_without_receipt=no_receipt,
    )
