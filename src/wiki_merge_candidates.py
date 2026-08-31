"""Is there anything here for synthesis to do? A local answer, before the spawn.

Measured on the live wiki (2026-08-31): the ``patterns`` topic holds 162 active
entries with ZERO duplicate titles and ZERO near-duplicate bodies. 3878 further
entries are already ``superseded`` — a ~24x compaction that has ALREADY
happened. The topic is not too big to compile; it is *finished*.

Asked to synthesize a set with nothing to merge, the model produced platitudes
for eleven days: 552 anchor-gate drops, ``entries_compiled: 0`` on all 27
maintenance runs, 87 model timeouts. The compile prompt already lists the exact
titles it kept emitting ("Use ``is None`` for optional sentinels") as DROP
examples, and the deterministic gate (#9954) dropped every one. Every part of
that pipeline behaved correctly. The mistake was upstream of all of it: the loop
decided to compile because the topic had *5 or more entries*, which says nothing
about whether synthesis can accomplish anything.

The barren ledger (#11888) catches this reactively — pay twice, then park for a
day, then probe again. This catches it before the first call, and costs nothing:
no model, no I/O, pure over entries the caller already loaded.

The estimator is a bottom-k shingle sketch rather than a full pairwise diff.
``gotchas`` holds 391 active entries — 76k pairs — and this runs on every tick
before deciding to spend anything, so it has to be cheap enough to be free.
Hashes are ``zlib.crc32``, not ``hash()``: str hashing is salted per process, so
``hash()`` would make the sketch — and therefore the verdict — differ between
runs of the same loop on the same content.
"""

from __future__ import annotations

import re
import zlib
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Tokens per shingle. Three is the usual prose default: long enough that
#: common word pairs do not collide, short enough to survive a light edit.
_SHINGLE = 3
#: Sketch width. Bottom-k over the shingle hashes: a uniform sample of the
#: document, so |A n B| / |A u B| over the sketches estimates the real Jaccard.
_SKETCH_K = 64

_NON_WORD = re.compile(r"\W+")


def _tokens(text: str) -> list[str]:
    return [t for t in _NON_WORD.sub(" ", text.casefold()).split() if t]


def _sketch(text: str) -> frozenset[int]:
    """Bottom-k hashes of *text*'s token shingles. Empty text yields nothing."""
    tokens = _tokens(text)
    if not tokens:
        return frozenset()
    if len(tokens) < _SHINGLE:
        grams = [" ".join(tokens)]
    else:
        grams = [
            " ".join(tokens[i : i + _SHINGLE])
            for i in range(len(tokens) - _SHINGLE + 1)
        ]
    hashes = {zlib.crc32(g.encode("utf-8")) for g in grams}
    return frozenset(sorted(hashes)[:_SKETCH_K])


def near_duplicate_pairs(
    bodies: Sequence[str], *, threshold: float
) -> list[tuple[int, int, float]]:
    """``(i, j, score)`` for every pair of *bodies* estimating above *threshold*.

    Takes plain strings, not entries: the tracked layout carries dicts and the
    legacy layout carries ``WikiEntry`` objects, and a predicate that has to
    know which is a predicate with two ways to be wired up wrong.

    Only pairs sharing at least one sketch hash are scored — the inverted index
    below is what keeps this out of quadratic territory on a real topic. Two
    documents with no shingle in common cannot clear any positive threshold, so
    skipping them changes no verdict.
    """
    if threshold <= 0 or len(bodies) < 2:
        return []
    sketches = [_sketch(body) for body in bodies]
    index: dict[int, list[int]] = defaultdict(list)
    for i, sketch in enumerate(sketches):
        for h in sketch:
            index[h].append(i)

    candidates: set[tuple[int, int]] = set()
    for holders in index.values():
        if len(holders) < 2:
            continue
        for a in range(len(holders)):
            for b in range(a + 1, len(holders)):
                candidates.add((holders[a], holders[b]))

    pairs: list[tuple[int, int, float]] = []
    for i, j in sorted(candidates):
        left, right = sketches[i], sketches[j]
        union = left | right
        if not union:
            continue
        score = len(left & right) / len(union)
        if score >= threshold:
            pairs.append((i, j, score))
    return pairs


def has_compaction_work(bodies: Sequence[str], *, threshold: float) -> bool:
    """True when synthesis has something to do: a merge to make.

    A merge is the ONLY job here that needs a model. The compile prompt's other
    job — dropping anchor-less platitudes — is already done deterministically
    one phase earlier by ``repo_wiki.flag_generic_entries_stale``, which scores
    every active entry with *the same* ``wiki_anchor_gate.has_repo_anchor``
    heuristic and flips the failures to ``stale``. Spending a synthesis spawn to
    repeat a pure function's work is the redundancy this whole check exists to
    remove, so an anchor-less entry is deliberately NOT counted as work.

    That distinction is load-bearing, and measurement is what found it: on the
    live wiki four of five topics have zero merge candidates but one or two
    anchor-less entries apiece. Counting those as work would have left this
    gate returning True almost always — a check that cannot fire.

    *threshold* of 0 disables the gate (everything is work), restoring the
    pre-#11898 behaviour.
    """
    if len(bodies) < 2:
        return False
    if threshold <= 0:
        return True
    return bool(near_duplicate_pairs(bodies, threshold=threshold))
