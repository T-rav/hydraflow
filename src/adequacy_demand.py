"""What the test-adequacy gate is allowed to *demand* (#11644).

#11643's calibration of the August implement corpus measured two properties of
the gate's demand, neither of which is about how strict the gate is:

1. **75 % of findings name nothing locatable** — 97 of 129 across 61 rejections
   carry no symbol, path, constant, flag or route. ``missing-error-path-coverage``,
   ``edge-case-coverage``, ``boundary-condition gap in truncation logic``. That
   text is exactly what the #11603 seam-1 repair loop hands back to the
   implementer as *"write exactly these missing tests"* — an instruction that
   cannot be followed because it does not say where.
2. **The bar moves between attempts** — 9 of 15 consecutive re-rejections
   demanded something entirely new, mean substantive overlap **0.04**. An
   implementer can satisfy every stated finding and still be rejected on a fresh
   set, which is what predicts the observed 37-of-46 non-recovery.

This module is the demand contract that answers both, and it deliberately
changes **what a finding may demand, not when the gate rejects**:

* :func:`is_anchored` — the anchoring predicate. Byte-identical to the lexical
  test ``adequacy_calibration.grade_finding`` scores the corpus with (that
  module imports these predicates rather than owning a second copy), so the
  instrument measures exactly what the runtime enforces. Deliberately *not*
  widened while it is the acceptance test: a looser predicate would move the
  #11643 baseline out from under the before/after comparison.
* :func:`evaluate_demand` — the retry pin. On a first attempt (no pinned
  demand) every finding blocks, exactly as before #11644. On a retry that
  carries the previous attempt's demand, the run is judged against **that**
  demand: a finding restating it blocks, a genuinely new finding blocks **only
  if it is anchored**, and a genuinely new *unanchored* finding — the 0.04
  pathology — is recorded as advisory instead of rejecting the run.

Strictness is untouched in every direction that matters: no verdict that names
a locatable gap is ever waived, and the deterministic coverage-delta source
never routes through here at all (its ``path:line`` findings are anchored by
construction and always block — see ``skill_gate.run_skill_check``).

Pure: no I/O, no config reads, no logging. The kill switch lives at the call
site (``test_adequacy_pin_demand``), passed in as ``pinned_enforced``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

#: Tokens shorter than this carry no topical signal in a findings string.
MIN_TOKEN_LENGTH = 4

#: How many findings ride forward as the pinned demand. Bounded for the same
#: reason ``TestAdequacyOutcome.findings`` is: the coverage delta can name
#: hundreds of lines and the pin is persisted in worker-result metadata.
MAX_PINNED_FINDINGS = 10

#: Ordinary English filler, dropped before any token comparison.
_STOPWORDS = frozenset(
    {
        "also",
        "both",
        "from",
        "into",
        "only",
        "over",
        "that",
        "this",
        "when",
        "then",
        "with",
    }
)

#: The gate's own vocabulary. These words appear in *nearly every* finding
#: ("untested X", "missing Y coverage", "boundary-condition gap") and say
#: nothing about **which** gap is being demanded, so leaving them in would
#: manufacture overlap between two rejections that asked for entirely different
#: things. Dropped for the same reason as ordinary stopwords: no discriminating
#: information. Kept deliberately small and greppable — words that do
#: discriminate ("error", "boundary", "wiring", "fallback") stay in.
_GATE_VOCABULARY = frozenset(
    {
        "branch",
        "branches",
        "case",
        "cases",
        "cover",
        "coverage",
        "covered",
        "edge",
        "edges",
        "gaps",
        "missing",
        "test",
        "tested",
        "testing",
        "tests",
        "uncovered",
        "unpinned",
        "untested",
    }
)

#: Phrases that make a demand *falsifiable*: a surviving mutant, a revert the
#: suite does not catch, a regression shown to pass silently. These are claims
#: about observed behaviour, not opinions about coverage — the only evidence
#: class #11643 found non-overlapping between the verifier and the plain finder.
_DEMONSTRATED_NEEDLES: tuple[str, ...] = (
    "mutant",
    "mutation",
    "survive",
    "revert-safe",
    "revert-safety",
    "silently inert if reverted",
    "demonstrated",
)

#: Patterns that anchor a demand to a concrete referent in the diff.
_NAMED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"`[^`]+`"),  # backticked code span
    re.compile(r"(?<![A-Za-z0-9])_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+"),  # snake_case
    re.compile(r"\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b"),  # CamelCase
    re.compile(r"\b[\w./-]+\.(?:py|sh|js|jsx|ts|tsx|yml|yaml|md|json)\b"),  # path
    re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b"),  # ALLCAPS constant
    re.compile(r"--[A-Za-z][\w-]*"),  # CLI flag
    re.compile(r"/api/[\w/-]+"),  # route
)


# --- the anchoring predicate ----------------------------------------------------


def cites_demonstration(finding: str) -> bool:
    """Does *finding* cite a concrete survivability demonstration?

    A mutant that lives, a revert the suite does not catch, a regression shown
    silent. Such a claim is checkable, so it anchors a demand even when it names
    no symbol.
    """
    lowered = finding.lower()
    return any(needle in lowered for needle in _DEMONSTRATED_NEEDLES)


def names_referent(finding: str) -> bool:
    """Does *finding* name something locatable in the diff?

    A symbol, path, constant, flag, route or backticked code span. This is a
    statement about the finding's *locatability*, not about whether the gap it
    describes is real.
    """
    return any(pattern.search(finding) for pattern in _NAMED_PATTERNS)


def is_anchored(finding: str) -> bool:
    """Can a repair pass mechanically act on *finding* from its own text?"""
    return cites_demonstration(finding) or names_referent(finding)


def split_findings(summary: str) -> tuple[str, ...]:
    """Split a rejection summary into findings at top-level separators only.

    Findings are comma- or semicolon-joined, but they routinely contain commas
    inside parentheses (``(skill/description/prompt)``) and inside backticked
    code spans, so the split tracks bracket depth and backtick parity. Empty
    fragments are dropped.

    Both readers use this: the live gate, when a failing verdict enumerated no
    ``GAPS:`` block and its demand is only in the summary line, and the
    calibration instrument, when recovering findings from a legacy manifest's
    ``error`` string. One definition, so what the gate judges is what the
    instrument scores.
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_code = False
    for char in summary:
        if char == "`":
            in_code = not in_code
        elif char in "([{" and not in_code:
            depth += 1
        elif char in ")]}" and not in_code:
            depth = max(0, depth - 1)
        if char in ",;" and depth == 0 and not in_code:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return tuple(p.strip() for p in parts if p.strip())


# --- tokenisation ---------------------------------------------------------------


def finding_tokens(text: str) -> frozenset[str]:
    """Topical tokens of a finding — lowercase words, stopwords/short ones out.

    The unit of comparison for "is this demand the one we already made?".
    Non-alphanumeric characters (backticks, underscores, hyphens) split, so
    ``_merge_base`` and ``merge-base`` produce the same tokens.
    """
    return frozenset(
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= MIN_TOKEN_LENGTH
        and token not in _STOPWORDS
        and token not in _GATE_VOCABULARY
    )


def demand_tokens(findings: Iterable[str]) -> frozenset[str]:
    """Union of every finding's topical tokens — one demand's vocabulary."""
    tokens: set[str] = set()
    for finding in findings:
        tokens |= finding_tokens(finding)
    return frozenset(tokens)


# --- the pin --------------------------------------------------------------------


def pin_findings(findings: Sequence[str]) -> tuple[str, ...]:
    """Reduce a failing verdict's findings to the demand carried to the retry.

    Blanks dropped, duplicates collapsed in first-seen order, bounded at
    :data:`MAX_PINNED_FINDINGS`.
    """
    seen: set[str] = set()
    pinned: list[str] = []
    for finding in findings:
        stripped = finding.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        pinned.append(stripped)
        if len(pinned) >= MAX_PINNED_FINDINGS:
            break
    return tuple(pinned)


# --- the demand contract --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DemandVerdict:
    """How one failing verdict's findings partition under the demand contract.

    ``blocking`` is the demand the run must close; everything else is recorded
    so the non-stationarity the fix addresses stays visible in telemetry rather
    than disappearing behind it.
    """

    #: Findings the run must close. Empty means the stated bar was met.
    blocking: tuple[str, ...] = ()
    #: Recorded, not blocking: new *and* unanchored on a pinned retry.
    advisory: tuple[str, ...] = ()
    #: Findings that restate the pinned demand. Empty when nothing is pinned.
    restated: tuple[str, ...] = ()
    #: Findings the pinned demand never mentioned. Empty when nothing is pinned.
    new: tuple[str, ...] = ()
    #: Every finding that names a locatable referent.
    anchored: tuple[str, ...] = ()
    #: Every finding that does not.
    unanchored: tuple[str, ...] = ()
    #: Whether a pinned demand was actually in force for this evaluation.
    pinned_enforced: bool = field(default=False)

    @property
    def blocks(self) -> bool:
        """Does this verdict still reject the run?"""
        return bool(self.blocking)


def evaluate_demand(
    findings: Sequence[str],
    pinned: Sequence[str] = (),
    *,
    pinned_enforced: bool = False,
) -> DemandVerdict:
    """Partition a failing verdict's *findings* against the *pinned* demand.

    With no pinned demand in force — a first attempt, or ``pinned_enforced``
    off — **every finding blocks**: identical to the pre-#11644 gate. The
    anchored/unanchored split is still reported, because the repair prompt
    orders its instructions by it and the instrument reads it back.

    With a pinned demand in force, attempt N+1 is judged against the findings
    attempt N actually stated:

    * a finding sharing topical vocabulary with the pin **restates** it and
      blocks — the stated bar has not been met;
    * a finding with no topical vocabulary at all cannot be *shown* disjoint
      from the pin, so it counts as restating it and blocks (conservative);
    * a genuinely new finding blocks **only when anchored** — the gate may
      raise a fresh bar, but only one it can point at;
    * a genuinely new *unanchored* finding is advisory: recorded in ``new`` and
      ``advisory``, and it does not reject the run.

    A pin whose own findings carry no topical tokens (every word shorter than
    :data:`MIN_TOKEN_LENGTH`, filler, or gate vocabulary) cannot discriminate
    anything, so it degenerates to "no pin in force" and every finding blocks.
    That is the safe direction — a demand that cannot be compared must never
    waive one — and :func:`adequacy_calibration.pinned_demand_overlap` drops
    such runs from its denominator rather than scoring them as disjoint.
    """
    anchored: list[str] = []
    unanchored: list[str] = []
    for finding in findings:
        (anchored if is_anchored(finding) else unanchored).append(finding)

    pinned_tokens = demand_tokens(pinned) if pinned_enforced else frozenset()
    if not pinned_tokens:
        # No pinned demand in force: the pre-#11644 shape, every finding blocks.
        return DemandVerdict(
            blocking=tuple(findings),
            anchored=tuple(anchored),
            unanchored=tuple(unanchored),
            pinned_enforced=False,
        )

    restated: list[str] = []
    new: list[str] = []
    for finding in findings:
        tokens = finding_tokens(finding)
        if not tokens or (tokens & pinned_tokens):
            restated.append(finding)
        else:
            new.append(finding)

    blocking = [*restated, *(f for f in new if is_anchored(f))]
    advisory = [f for f in new if not is_anchored(f)]
    return DemandVerdict(
        blocking=tuple(blocking),
        advisory=tuple(advisory),
        restated=tuple(restated),
        new=tuple(new),
        anchored=tuple(anchored),
        unanchored=tuple(unanchored),
        pinned_enforced=True,
    )
