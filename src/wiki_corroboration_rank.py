"""Pure candidate ranking for the wiki corroboration hook (#11606).

``WikiCompiler.dedup_or_corroborate`` asks an LLM whether an entry being
ingested re-states a principle an existing entry already carries. It can only
ask about the entries it is handed, and handing it a *bounded* set is what
keeps one ingest from firing an LLM call per entry in the topic.

Before #11606 that bound was a positional ``[:5]`` slice in filename order,
which made corroboration a function of where an entry happened to sort rather
than of what it said: across the live wiki's 681 loadable active entries,
every corroboration on record sat at index 0-4, and not one of the 661
entries past the window had ever been corroborated. The same few entries
absorbed every bump, on whatever thin lexical resemblance a model under
instruction to find a match could locate.

This module is the deterministic pre-filter that replaces it. It is kept
separate from ``wiki_compiler`` because it is pure, cheap, and unit-testable
without a model: no LLM, no I/O, no config.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from repo_wiki import WikiEntry

__all__ = [
    "MIN_CANDIDATE_SIMILARITY",
    "candidate_similarity",
    "rank_corroboration_candidates",
]

_TOKEN_RE = re.compile(r"[a-z0-9_]+")

#: Words carrying no topical signal in wiki rule prose. Dropped before
#: scoring so two entries do not look alike merely because both are written
#: in the mandated "Rule / Example / **Why:**" house voice.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "is", "are",
    "be", "not", "must", "with", "that", "this", "it", "as", "at", "by", "from",
    "when", "if", "so", "no", "any", "all", "use", "using", "only", "its",
    "than", "then", "but", "can", "will", "has", "have", "had", "was", "were",
    "one", "two", "new", "per", "via", "into", "them", "they", "their", "you",
    "your", "we", "our", "do", "does", "done", "just", "also", "each", "other",
    "same", "such", "more", "most", "should", "would", "could", "may", "might",
    "need", "needs", "every", "never", "always", "already", "still", "even",
    "after", "before", "during", "while", "because", "since", "which", "what",
    "who", "how", "why", "where", "there", "here", "both", "either", "neither",
    "between", "across", "over", "under", "out", "off", "again", "once",
    "about", "against", "without", "within", "through",
})  # fmt: skip

#: Minimum Jaccard overlap for an existing entry to be worth an LLM
#: same-principle judgement.
#:
#: Calibrated against the live repo wiki (1,122 active entries across four
#: topics): the median entry's best match scores ~0.12 and a true
#: re-discovery pair scores ~0.19, while the #11606 escape — entry 2609
#: (escape-ledger per-tick budget) corroborated by a #11518 CodeQL
#: cache-poisoning review entry — scores 0.011, ranking 241st of 325.
#:
#: The floor is deliberately biased toward false negatives. A missed
#: corroboration only writes a sibling entry the topic compiler later merges;
#: a false one silently inflates a trust signal that readers, and the
#: ``(+N)`` suffix shown next to every entry, have no way to audit.
MIN_CANDIDATE_SIMILARITY = 0.10


def _tokens(entry: WikiEntry) -> set[str]:
    """Topical token set for one entry — lowercased, stopped, length-filtered."""
    text = f"{entry.title}\n{entry.content}".lower()
    return {
        token
        for token in _TOKEN_RE.findall(text)
        if len(token) > 2 and token not in _STOPWORDS
    }


def candidate_similarity(entry: WikiEntry, other: WikiEntry) -> float:
    """Jaccard overlap of two entries' topical tokens, in ``[0.0, 1.0]``.

    Deterministic and dependency-free on purpose: this runs before any LLM
    call, so it must be cheap enough to score a whole topic on every ingest
    and stable enough to pin in a unit test.
    """
    left, right = _tokens(entry), _tokens(other)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def rank_corroboration_candidates(
    entry: WikiEntry,
    existing: list[tuple[WikiEntry, Path]],
    *,
    limit: int,
    min_similarity: float = MIN_CANDIDATE_SIMILARITY,
) -> list[tuple[WikiEntry, Path]]:
    """The ``limit`` entries most similar to *entry*, floor-filtered.

    Returns fewer than ``limit`` — possibly none — when nothing clears
    ``min_similarity``. An empty result is the correct answer for a genuinely
    novel entry: it skips the LLM call entirely rather than asking it to pick
    a winner out of entries that have nothing to do with the subject.

    Ties keep the caller's incoming order, so the result is deterministic.
    """
    if limit <= 0:
        return []
    scored = [
        (candidate_similarity(entry, other), index, other, path)
        for index, (other, path) in enumerate(existing)
    ]
    ranked = sorted(
        (item for item in scored if item[0] >= min_similarity),
        key=lambda item: (-item[0], item[1]),
    )
    return [(other, path) for _score, _index, other, path in ranked[:limit]]
