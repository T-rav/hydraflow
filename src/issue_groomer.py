"""Pure engine for IssueGroomerLoop: index, dup-candidate prefilter, judged-pair cache.

No I/O, no LLM spawns — stdlib only (``dataclasses``, ``difflib``, ``hashlib``,
``itertools``, ``re``). Callers (the loop, ports) build ``GroomIssue`` from
whatever the backlog read returns; this module only reasons about content.

Determinism is load-bearing: ``find_dup_candidates`` must return the same
list, in the same order, given the same inputs — see
docs/superpowers/specs/2026-07-19-issue-groomer-loop-design.md §2.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

# Title/body scoring weights and gate. Tuned in the design spec §2 — a pair
# scores 0.6 on title similarity + 0.4 on body token overlap, and anything
# below the floor isn't worth a judged LLM call.
TITLE_WEIGHT = 0.6
BODY_WEIGHT = 0.4
SCORE_FLOOR = 0.35

# Words this short (issue numbers, "an", "the", ...) are too common to signal
# duplication, so the body-overlap Jaccard set only keeps words longer than
# this many characters.
MIN_TOKEN_LEN = 3

# Issue-ref numbers ("#12345") are noise for title similarity — a title
# quoting another issue number shouldn't be treated as textually similar to
# that issue. Numbers this long or longer are assumed to be refs; shorter
# numbers (version numbers, small counts) are kept.
MIN_ISSUE_REF_DIGITS = 5

_ISSUE_REF_RE = re.compile(rf"\b\d{{{MIN_ISSUE_REF_DIGITS},}}\b")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+")


@dataclass(frozen=True)
class GroomIssue:
    """Engine-side view of one backlog issue, built from the port item."""

    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    updated_at: str


@dataclass(frozen=True)
class CandidatePair:
    """A scored, unjudged duplicate candidate. ``a`` < ``b`` always."""

    a: int
    b: int
    score: float


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation and issue-ref numbers, collapse whitespace."""
    lowered = title.lower()
    without_refs = _ISSUE_REF_RE.sub(" ", lowered)
    without_punct = _PUNCT_RE.sub(" ", without_refs)
    return _WHITESPACE_RE.sub(" ", without_punct).strip()


def body_hash(body: str) -> str:
    """Sha1 of the normalized body, truncated to the first 12 hex chars."""
    normalized = _WHITESPACE_RE.sub(" ", body.lower()).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def pair_key(a: GroomIssue, b: GroomIssue) -> str:
    """Cache key for a judged pair: ``lo:hi:hash(lo.body):hash(hi.body)``.

    A body edit on EITHER side changes its hash and thus the whole key,
    invalidating any cached judgment for the pair.
    """
    lo, hi = (a, b) if a.number <= b.number else (b, a)
    return f"{lo.number}:{hi.number}:{body_hash(lo.body)}:{body_hash(hi.body)}"


def _tokenize(body: str) -> frozenset[str]:
    return frozenset(
        w for w in _WORD_RE.findall(body.lower()) if len(w) > MIN_TOKEN_LEN
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _score(a: GroomIssue, b: GroomIssue) -> float:
    title_ratio = SequenceMatcher(
        None, normalize_title(a.title), normalize_title(b.title)
    ).ratio()
    body_overlap = _jaccard(_tokenize(a.body), _tokenize(b.body))
    return TITLE_WEIGHT * title_ratio + BODY_WEIGHT * body_overlap


def find_dup_candidates(
    issues: Sequence[GroomIssue],
    changed: set[int],
    judged: set[str],
    budget: int,
) -> list[CandidatePair]:
    """Score every pair with ≥1 changed side, drop judged/low-score pairs.

    Sort is ``(-score, a, b)`` so ties break on issue number — the same
    inputs always produce the same list, in the same order.
    """
    candidates: list[CandidatePair] = []
    for x, y in itertools.combinations(issues, 2):
        if x.number not in changed and y.number not in changed:
            continue
        key = pair_key(x, y)
        if key in judged:
            continue
        score = _score(x, y)
        if score < SCORE_FLOOR:
            continue
        lo, hi = (x.number, y.number) if x.number <= y.number else (y.number, x.number)
        candidates.append(CandidatePair(a=lo, b=hi, score=score))

    candidates.sort(key=lambda c: (-c.score, c.a, c.b))
    return candidates[:budget]
