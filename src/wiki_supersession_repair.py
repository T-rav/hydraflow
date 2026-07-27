"""Pure planner + applier for repairing the repo wiki's supersession graph.

``WikiCompiler.compile_topic_tracked`` (``src/wiki_compiler.py``) historically
wrote a *cartesian* ``supersedes`` / ``superseded_by`` mapping: every
synthesis entry in a batch claimed to supersede every input entry in that
batch, and every input entry was pointed at only the first synthesis entry
regardless of topical fit (issue #10566, forward-fixed but not yet
data-repaired in the existing tracked wiki). Following a superseded entry's
``superseded_by`` pointer can therefore land on an unrelated sibling.

This module re-derives the correct 1:1 edges from each round's H1 titles and
plans a frontmatter-only rewrite. A "round" for a given superseded entry is
the set of sibling entries whose *current* ``supersedes`` list names it —
under the cartesian bug, that is exactly the batch of synthesis outputs
written by one ``compile_topic_tracked`` call. Within a round, an entry is
re-pointed only when exactly one sibling shares its H1 title; anything
ambiguous (2+ title matches) or unmatched (a genuine N-to-1 merge, per
``docs/wiki/gotchas.md``'s fail-safe-abort convention) is left untouched and
reported rather than guessed (issue #10572).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from repo_wiki import split_tracked_entry

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackedFile:
    """One parsed tracked-layout wiki entry file."""

    id: str
    title: str
    status: str
    superseded_by: str | None
    supersedes: tuple[str, ...]
    path: Path
    fields: dict[str, str]
    body: str


def _parse_supersedes(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def load_topic_entries(topic_dir: Path) -> list[TrackedFile]:
    """Parse every ``*.md`` file in ``topic_dir`` — active *and* superseded.

    Unlike ``repo_wiki._load_tracked_active_entries``, this does not filter
    to ``status: active``: the repair planner needs superseded entries
    (predecessors) and their would-be successors alike, and a successor from
    one round can itself be superseded by a later round.
    """
    if not topic_dir.is_dir():
        return []
    out: list[TrackedFile] = []
    for path in sorted(topic_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fields, _block, body = split_tracked_entry(text)
        if not fields:
            continue
        title = body.lstrip().split("\n", 1)[0].lstrip("# ").strip() or path.stem
        out.append(
            TrackedFile(
                id=fields.get("id", ""),
                title=title,
                status=fields.get("status", "active"),
                superseded_by=fields.get("superseded_by") or None,
                supersedes=_parse_supersedes(fields.get("supersedes")),
                path=path,
                fields=fields,
                body=body,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

# Reason an entry's superseded_by target was (or wasn't) changed.
#   matched         - exactly one same-titled sibling in its round
#   left_on_primary - no title match; genuine N-to-1 merge, left untouched
#   ambiguous       - 2+ same-titled siblings in its round, left untouched
#   unclaimed       - no sibling's supersedes currently names this id
Reason = str


@dataclass(frozen=True)
class Repoint:
    """A ``superseded_by`` repointing decision for one superseded entry."""

    entry_id: str
    path: Path
    old_target: str | None
    new_target: str | None
    reason: Reason

    @property
    def changed(self) -> bool:
        return self.new_target != self.old_target


@dataclass(frozen=True)
class SupersedesRewrite:
    """A ``supersedes`` rewrite decision for one successor entry."""

    entry_id: str
    path: Path
    old_ids: tuple[str, ...]
    new_ids: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.new_ids != self.old_ids


@dataclass
class TopicRepairPlan:
    topic: str
    repoints: list[Repoint] = field(default_factory=list)
    rewrites: list[SupersedesRewrite] = field(default_factory=list)

    @property
    def changed_repoints(self) -> list[Repoint]:
        return [r for r in self.repoints if r.changed]

    @property
    def changed_rewrites(self) -> list[SupersedesRewrite]:
        return [r for r in self.rewrites if r.changed]


def plan_topic_repair(topic_dir: Path, *, topic: str) -> TopicRepairPlan:
    """Plan the supersession-graph repair for one topic directory.

    Pure: reads the files under ``topic_dir`` but never writes. Pass the
    result to :func:`apply_repair_plan` to write it.
    """
    entries = load_topic_entries(topic_dir)

    # round(E) = every entry whose *current* supersedes list names E.id.
    rounds: dict[str, list[TrackedFile]] = {e.id: [] for e in entries if e.id}
    for successor in entries:
        for old_id in successor.supersedes:
            if old_id in rounds:
                rounds[old_id].append(successor)

    plan = TopicRepairPlan(topic=topic)
    final_target: dict[str, str | None] = {}

    for entry in entries:
        if entry.status != "superseded" or not entry.id:
            continue

        round_ = rounds.get(entry.id, [])
        if not round_:
            plan.repoints.append(
                Repoint(
                    entry.id,
                    entry.path,
                    entry.superseded_by,
                    entry.superseded_by,
                    "unclaimed",
                )
            )
            final_target[entry.id] = entry.superseded_by
            continue

        matches = [
            s
            for s in round_
            if s.id != entry.id and s.title.strip() == entry.title.strip()
        ]
        if len(matches) == 1:
            new_target: str | None = matches[0].id
            reason: Reason = "matched"
        elif len(matches) == 0:
            new_target = entry.superseded_by
            reason = "left_on_primary"
        else:
            new_target = entry.superseded_by
            reason = "ambiguous"

        plan.repoints.append(
            Repoint(entry.id, entry.path, entry.superseded_by, new_target, reason)
        )
        final_target[entry.id] = new_target

    # Rebuild every successor's supersedes list from the final repointing
    # decisions above, so it contains exactly the ids now pointing at it.
    for successor in entries:
        if not successor.supersedes or not successor.id:
            continue
        new_ids = tuple(
            sorted(
                pid for pid, target in final_target.items() if target == successor.id
            )
        )
        plan.rewrites.append(
            SupersedesRewrite(
                successor.id, successor.path, successor.supersedes, new_ids
            )
        )

    return plan


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def apply_repair_plan(plan: TopicRepairPlan) -> int:
    """Write only the changed ``superseded_by`` / ``supersedes`` fields.

    Only frontmatter is touched — body bytes and every other frontmatter
    key are byte-identical afterwards. Returns the number of files written.
    """
    updates: dict[Path, dict[str, str | None]] = {}
    for repoint in plan.changed_repoints:
        updates.setdefault(repoint.path, {})["superseded_by"] = repoint.new_target
    for rewrite in plan.changed_rewrites:
        updates.setdefault(rewrite.path, {})["supersedes"] = (
            ",".join(rewrite.new_ids) if rewrite.new_ids else None
        )

    for path, field_updates in updates.items():
        _apply_field_updates(path, field_updates)
    return len(updates)


def _apply_field_updates(path: Path, field_updates: dict[str, str | None]) -> None:
    from file_util import atomic_write  # noqa: PLC0415

    text = path.read_text(encoding="utf-8")
    fields, _block, body = split_tracked_entry(text)
    if not fields:
        return
    for key, value in field_updates.items():
        if value is None:
            fields.pop(key, None)
        else:
            fields[key] = value
    rebuilt = (
        "---\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n---\n" + body
    )
    atomic_write(path, rebuilt)


# ---------------------------------------------------------------------------
# Repo-wide orchestration
# ---------------------------------------------------------------------------


def discover_topics(tracked_root: Path, repo: str) -> list[str]:
    """Directory-scan for topic subdirectories under ``tracked_root/repo``.

    A new topic directory is picked up automatically — no hardcoded list.
    """
    repo_dir = tracked_root / repo
    if not repo_dir.is_dir():
        return []
    return sorted(p.name for p in repo_dir.iterdir() if p.is_dir())


@dataclass(frozen=True)
class RepairReport:
    topic: str
    total_superseded: int
    matched: int
    left_on_primary: int
    ambiguous: int
    unclaimed: int
    supersedes_lists_rewritten: int


def summarize_plan(plan: TopicRepairPlan) -> RepairReport:
    by_reason = Counter(r.reason for r in plan.repoints)
    return RepairReport(
        topic=plan.topic,
        total_superseded=len(plan.repoints),
        matched=by_reason.get("matched", 0),
        left_on_primary=by_reason.get("left_on_primary", 0),
        ambiguous=by_reason.get("ambiguous", 0),
        unclaimed=by_reason.get("unclaimed", 0),
        supersedes_lists_rewritten=len(plan.changed_rewrites),
    )
