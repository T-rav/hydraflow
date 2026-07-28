"""Content-completeness auditor for N-to-1 wiki supersession merges.

Issue #10655 asked for a completeness check that flags predecessors in a
genuine N-to-1 merge — ``reason == "left_on_primary"`` in
:func:`wiki_supersession_repair.plan_topic_repair` — whose *content* has no
discernible representation in the successor's body. PR #10693 closed #10655
with an unrelated ``fixed_in_pr`` dedup fix; the check itself never shipped
(#10757). This module is that check.

The supersession planner records pointer moves, not content survival: when a
round of synthesis entries supersedes many predecessors, each predecessor is
re-pointed to the one successor whose H1 title matched. A predecessor with no
title match (``left_on_primary``) is left pointing at the round's primary —
whose body may paraphrase away every lesson but its own. The lesson silently
leaves the active corpus.

This module tiers each ``left_on_primary`` predecessor by *lesson survival*:

* ``represented`` — every live code anchor the predecessor cites also appears
  in the live terminal successor's body.
* ``weak``        — some, but not all, live anchors survive.
* ``orphaned``    — the predecessor has live anchors, none survive: a durable
  lesson has silently left the active corpus (e.g. ``gotchas/0841``, #10758).
* ``no_anchor``   — the predecessor cites no code anchors, so survival cannot
  be measured from cites (counted, not tiered).
* ``not_live``    — every anchor the predecessor cites is a dangling cite that
  no longer resolves against live code (counted, suppressed: reviving these
  would re-import broken cites and trip ``WikiRotDetectorLoop``, #10758).

An *anchor* is a code symbol the predecessor cites, drawn from its
``code_refs`` frontmatter and from Style-A/Style-B cites in its body
(:func:`wiki_rot_citations.extract_cites`). ``[[wikilinks]]`` are stripped
from the successor body before the containment test — a dangling pointer to an
anchor page is not the lesson itself (``gotchas/0841`` survives only as
``[[git_log_marker_splitlines_gotcha]]``, an anchor page that was never
created).

Pure + read-only. Consumes :func:`plan_topic_repair`'s output at call time
(``architecture/0241``) rather than stored ``superseded_by`` pointers, so it
works both before and after #10572's repair is applied to live data. Callers:
the one-shot CLI ``scripts/audit_wiki_lesson_coverage.py`` (#10758) and the
continuous ``WikiRotDetectorLoop`` gate (#10763).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from wiki_rot_citations import extract_cites, module_symbols
from wiki_supersession_repair import (
    TopicRepairPlan,
    TrackedFile,
    discover_topics,
    load_topic_entries,
    plan_topic_repair,
)

# Tier labels — see module docstring.
TIER_REPRESENTED = "represented"
TIER_WEAK = "weak"
TIER_ORPHANED = "orphaned"
TIER_NO_ANCHOR = "no_anchor"
TIER_NOT_LIVE = "not_live"

# Wikilink targets are pointers, not content: ``[[anchor_page]]``.
_WIKILINK_RE = re.compile(r"\[\[[^\]]*\]\]")


def strip_wikilinks(text: str) -> str:
    """Blank out ``[[...]]`` wikilink targets so a pointer is not counted as
    representation of the thing it points at."""
    return _WIKILINK_RE.sub(" ", text)


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    """One code symbol a wiki entry cites as the concrete home of its lesson.

    ``module_path`` is a slashed ``.py`` path (empty when unknown); ``symbol``
    is the cited identifier; ``raw`` is the verbatim cite for display.
    """

    module_path: str
    symbol: str
    raw: str


def _parse_code_refs(raw: str | None) -> list[Anchor]:
    """Parse a ``code_refs`` frontmatter value (``path.py:symbol,...``)."""
    if not raw:
        return []
    out: list[Anchor] = []
    for part in raw.split(","):
        ref = part.strip()
        if not ref or ":" not in ref:
            continue
        module_path, _, symbol = ref.rpartition(":")
        module_path = module_path.strip()
        symbol = symbol.strip()
        if not module_path or not symbol or symbol.isdigit():
            continue
        out.append(Anchor(module_path=module_path, symbol=symbol, raw=ref))
    return out


def entry_anchors(entry: TrackedFile) -> list[Anchor]:
    """Return the deduplicated code anchors *entry* cites.

    Two sources are merged: the ``code_refs`` frontmatter field (the
    machine-readable convention, mirrors ``supersedes``) and Style-A/Style-B
    hard cites in the body (:func:`extract_cites`). Deduplicated by
    ``(module_path, symbol)``.
    """
    seen: set[tuple[str, str]] = set()
    out: list[Anchor] = []
    for anchor in _parse_code_refs(entry.fields.get("code_refs")):
        key = (anchor.module_path, anchor.symbol)
        if key in seen:
            continue
        seen.add(key)
        out.append(anchor)
    for cite in extract_cites(entry.body):
        module_path = cite.module_as_path()
        if not module_path:
            continue
        key = (module_path, cite.symbol)
        if key in seen:
            continue
        seen.add(key)
        out.append(Anchor(module_path=module_path, symbol=cite.symbol, raw=cite.raw))
    return out


class SymbolIndex:
    """Cached ``module_path -> defined-symbol set`` index over a checked-out repo.

    One index is built per run so the corpus-wide audit parses each source
    module at most once, rather than re-parsing per anchor across the ~471
    ``left_on_primary`` predecessors (#10758).
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root
        self._cache: dict[str, frozenset[str]] = {}

    def module_symbols(self, module_path: str) -> frozenset[str]:
        cached = self._cache.get(module_path)
        if cached is not None:
            return cached
        syms = module_symbols(self._repo_root, module_path)
        self._cache[module_path] = syms
        return syms

    def resolves(self, anchor: Anchor) -> bool:
        """``True`` iff *anchor* names a symbol live code still defines."""
        if not anchor.module_path or not anchor.symbol:
            return False
        return anchor.symbol in self.module_symbols(anchor.module_path)


# ---------------------------------------------------------------------------
# Terminal resolution
# ---------------------------------------------------------------------------


def resolve_terminal(entry: TrackedFile, by_id: dict[str, TrackedFile]) -> TrackedFile:
    """Follow *entry*'s ``superseded_by`` chain to the live terminal successor.

    Stops at the first entry with no resolvable ``superseded_by`` target (the
    active terminal, or a dangling pointer). Cycle-safe: a revisited id ends
    the walk (#10758 found all 471 edges resolve with 0 cycles, but the guard
    keeps a corrupt graph from looping).
    """
    visited: set[str] = set()
    current = entry
    while True:
        if current.id in visited:
            return current
        visited.add(current.id)
        next_id = current.superseded_by
        if not next_id or next_id not in by_id:
            return current
        current = by_id[next_id]


# ---------------------------------------------------------------------------
# Per-predecessor verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PredecessorCoverage:
    """Lesson-survival verdict for one ``left_on_primary`` predecessor."""

    topic: str
    predecessor_id: str
    predecessor_path: Path
    terminal_id: str
    terminal_path: Path
    tier: str
    live_anchors: tuple[str, ...]
    surviving_anchors: tuple[str, ...]
    not_live_anchors: tuple[str, ...]
    containment: float

    def to_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "predecessor_id": self.predecessor_id,
            "predecessor_path": str(self.predecessor_path),
            "terminal_id": self.terminal_id,
            "terminal_path": str(self.terminal_path),
            "tier": self.tier,
            "live_anchors": list(self.live_anchors),
            "surviving_anchors": list(self.surviving_anchors),
            "not_live_anchors": list(self.not_live_anchors),
            "containment": round(self.containment, 4),
        }


def assess_predecessor_coverage(
    predecessor: TrackedFile,
    terminal: TrackedFile,
    index: SymbolIndex,
    *,
    topic: str,
) -> PredecessorCoverage:
    """Tier one predecessor by whether its lesson survives into *terminal*.

    Containment is measured only over anchors that still resolve to live code
    (``live_anchors``): a dangling cite is neither the lesson nor evidence it
    was dropped. ``[[wikilinks]]`` are stripped from the terminal body first.
    """
    anchors = entry_anchors(predecessor)
    live = [a for a in anchors if index.resolves(a)]
    not_live = [a for a in anchors if not index.resolves(a)]
    live_symbols = tuple(dict.fromkeys(a.symbol for a in live))
    not_live_symbols = tuple(dict.fromkeys(a.symbol for a in not_live))

    haystack = strip_wikilinks(terminal.body)
    surviving = tuple(s for s in live_symbols if s in haystack)
    containment = len(surviving) / len(live_symbols) if live_symbols else 0.0

    if not anchors:
        tier = TIER_NO_ANCHOR
    elif not live_symbols:
        tier = TIER_NOT_LIVE
    elif containment >= 1.0:
        tier = TIER_REPRESENTED
    elif containment <= 0.0:
        tier = TIER_ORPHANED
    else:
        tier = TIER_WEAK

    return PredecessorCoverage(
        topic=topic,
        predecessor_id=predecessor.id,
        predecessor_path=predecessor.path,
        terminal_id=terminal.id,
        terminal_path=terminal.path,
        tier=tier,
        live_anchors=live_symbols,
        surviving_anchors=surviving,
        not_live_anchors=not_live_symbols,
        containment=containment,
    )


# ---------------------------------------------------------------------------
# Per-topic report
# ---------------------------------------------------------------------------


@dataclass
class TopicCoverageReport:
    topic: str
    verdicts: list[PredecessorCoverage] = field(default_factory=list)

    @property
    def tier_counts(self) -> dict[str, int]:
        return dict(Counter(v.tier for v in self.verdicts))

    def orphaned(self) -> list[PredecessorCoverage]:
        return [v for v in self.verdicts if v.tier == TIER_ORPHANED]

    def to_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "tier_counts": self.tier_counts,
            "verdicts": [v.to_dict() for v in self.verdicts],
        }


def _index_entries(
    entries: list[TrackedFile],
) -> tuple[dict[str, TrackedFile], dict[Path, TrackedFile]]:
    """Index topic entries by id and by path.

    Ids are unique only within a topic — and even there the corpus carries
    collisions (#10753). On an id clash, prefer an ``active`` entry so the
    terminal walk lands on a live page rather than a stale duplicate.
    """
    by_id: dict[str, TrackedFile] = {}
    by_path: dict[Path, TrackedFile] = {}
    for entry in entries:
        by_path[entry.path] = entry
        if not entry.id:
            continue
        incumbent = by_id.get(entry.id)
        if incumbent is None or (
            incumbent.status != "active" and entry.status == "active"
        ):
            by_id[entry.id] = entry
    return by_id, by_path


def assess_topic_coverage(
    plan: TopicRepairPlan,
    topic_dir: Path,
    repo_root: Path,
    *,
    index: SymbolIndex | None = None,
) -> TopicCoverageReport:
    """Tier every ``left_on_primary`` predecessor in *plan* by lesson survival.

    Reads the topic entries from *topic_dir* and resolves anchor liveness
    against *repo_root* (the checked-out source tree). Only predecessors the
    plan classified ``left_on_primary`` are tiered — matched, ambiguous, and
    unclaimed edges are out of scope.
    """
    index = index or SymbolIndex(repo_root)
    entries = load_topic_entries(topic_dir)
    by_id, by_path = _index_entries(entries)

    report = TopicCoverageReport(topic=plan.topic)
    for repoint in plan.repoints:
        if repoint.reason != "left_on_primary":
            continue
        predecessor = by_path.get(repoint.path)
        if predecessor is None:
            continue
        terminal = resolve_terminal(predecessor, by_id)
        report.verdicts.append(
            assess_predecessor_coverage(predecessor, terminal, index, topic=plan.topic)
        )
    return report


# ---------------------------------------------------------------------------
# Repo-wide report
# ---------------------------------------------------------------------------


@dataclass
class RepoCoverageReport:
    repo: str
    topics: list[TopicCoverageReport] = field(default_factory=list)

    @property
    def tier_counts(self) -> dict[str, int]:
        totals: Counter[str] = Counter()
        for topic in self.topics:
            totals.update(topic.tier_counts)
        return dict(totals)

    def orphaned(self) -> list[PredecessorCoverage]:
        out: list[PredecessorCoverage] = []
        for topic in self.topics:
            out.extend(topic.orphaned())
        return out

    def to_dict(self) -> dict[str, object]:
        return {
            "repo": self.repo,
            "tier_counts": self.tier_counts,
            "topics": [t.to_dict() for t in self.topics],
            "orphaned": [v.to_dict() for v in self.orphaned()],
        }


def assess_repo_coverage(
    tracked_root: Path,
    repo: str,
    repo_root: Path,
    *,
    topics: list[str] | None = None,
) -> RepoCoverageReport:
    """Run the lesson-coverage audit across every topic of one tracked wiki.

    A single :class:`SymbolIndex` is shared across topics so each source
    module is parsed at most once for the whole run.
    """
    index = SymbolIndex(repo_root)
    topic_names = topics or discover_topics(tracked_root, repo)
    report = RepoCoverageReport(repo=repo)
    for topic in sorted(topic_names):
        topic_dir = tracked_root / repo / topic
        plan = plan_topic_repair(topic_dir, topic=topic)
        report.topics.append(
            assess_topic_coverage(plan, topic_dir, repo_root, index=index)
        )
    return report
