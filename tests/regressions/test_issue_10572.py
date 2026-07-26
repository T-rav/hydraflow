"""Regression test for #10572.

``WikiCompiler.compile_topic_tracked`` (src/wiki_compiler.py) historically
wrote a cartesian supersedes/superseded_by mapping: every synthesis entry in
a batch claimed to supersede every input entry in that batch, and every
input entry was pointed at only the *first* synthesis id regardless of
topical fit (issue #10566). The write path is forward-fixed, but ~2064
already-corrupted entries remain in the live tracked wiki under
``repo_wiki/T-rav/hydraflow/{testing,gotchas,patterns}/`` — this issue is
the one-shot data repair.

This replays the same five-entry cartesian shape #10566's own regression
test used (cross-dependency mapping, DependabotMergeLoop guidance,
TrustFleetSanityLoop guidance, ADR-drift citations, JsonlLedger split),
corrupted the same way a real ``compile_topic_tracked`` batch corrupts it,
and asserts ``wiki_supersession_repair`` re-derives the correct per-title
edges instead of leaving every old entry pointed at the arbitrary first
synthesis id.
"""

from __future__ import annotations

from pathlib import Path

from wiki_supersession_repair import (
    apply_repair_plan,
    load_topic_entries,
    plan_topic_repair,
)

REPO = "acme/widget"

_OLD_TOPICS = [
    ("0011", "Cross-dependency mapping"),
    ("0012", "DependabotMergeLoop guidance"),
    ("0013", "TrustFleetSanityLoop guidance"),
    ("0014", "ADR-drift citations"),
    ("0015", "JsonlLedger split"),
]
_NEW_IDS = ["0017", "0018", "0019", "0020", "0021"]


def _write_entry(
    topic_dir: Path,
    *,
    entry_id: str,
    title: str,
    status: str = "active",
    superseded_by: str | None = None,
    supersedes: list[str] | None = None,
) -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {entry_id}",
        "topic: dependencies",
        "source_issue: synthesis",
        "source_phase: synthesis",
        "created_at: 2026-01-01T00:00:00+00:00",
        f"status: {status}",
        "corroborations: 1",
    ]
    if superseded_by is not None:
        lines.append(f"superseded_by: {superseded_by}")
    if supersedes:
        lines.append("supersedes: " + ",".join(supersedes))
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"Body content for {entry_id}.")
    lines.append("")
    path = topic_dir / f"{entry_id}-issue-1-x.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestSupersessionRepairFixesCartesianMapping:
    """End-to-end: replays the exact five-entry shape #10566's own test used."""

    def _build_corrupted_topic(self, tmp_path: Path) -> Path:
        topic_dir = tmp_path / "repo_wiki" / REPO / "dependencies"
        old_ids = [old_id for old_id, _ in _OLD_TOPICS]
        primary_id = _NEW_IDS[0]

        for old_id, title in _OLD_TOPICS:
            _write_entry(
                topic_dir,
                entry_id=old_id,
                title=title,
                status="superseded",
                superseded_by=primary_id,
            )
        # Every synthesis output claims to supersede all five old ids —
        # the cartesian bug — even though each one is only the true
        # topical replacement for the sibling that shares its title.
        for new_id, (_, title) in zip(_NEW_IDS, _OLD_TOPICS, strict=True):
            _write_entry(topic_dir, entry_id=new_id, title=title, supersedes=old_ids)

        return topic_dir

    def test_repair_repoints_each_old_entry_to_its_own_topical_match(
        self, tmp_path: Path
    ) -> None:
        topic_dir = self._build_corrupted_topic(tmp_path)

        plan = plan_topic_repair(topic_dir, topic="dependencies")
        touched = apply_repair_plan(plan)
        # 0011 (index 0) already happened to point at its true match (0017,
        # the cartesian primary) so it isn't rewritten; the other four old
        # entries repoint, and all five new entries get trimmed.
        assert touched == (len(_OLD_TOPICS) - 1) + len(_NEW_IDS)

        entries = {e.id: e for e in load_topic_entries(topic_dir)}
        new_id_by_old_id = dict(
            zip([oid for oid, _ in _OLD_TOPICS], _NEW_IDS, strict=True)
        )

        for old_id, _ in _OLD_TOPICS:
            old_entry = entries[old_id]
            assert old_entry.status == "superseded"
            assert old_entry.superseded_by == new_id_by_old_id[old_id]

        # Every new entry's supersedes list is trimmed to exactly the one
        # old id whose title it actually matches — not all five.
        for new_id, (old_id, _) in zip(_NEW_IDS, _OLD_TOPICS, strict=True):
            assert entries[new_id].supersedes == (old_id,)

        # No dangling superseded_by: every target id resolves to a real file.
        for old_id, _ in _OLD_TOPICS:
            assert entries[old_id].superseded_by in entries

    def test_repair_is_idempotent(self, tmp_path: Path) -> None:
        topic_dir = self._build_corrupted_topic(tmp_path)

        first_plan = plan_topic_repair(topic_dir, topic="dependencies")
        apply_repair_plan(first_plan)

        second_plan = plan_topic_repair(topic_dir, topic="dependencies")
        assert second_plan.changed_repoints == []
        assert second_plan.changed_rewrites == []
        assert apply_repair_plan(second_plan) == 0

    def test_superseded_count_unchanged_before_and_after(self, tmp_path: Path) -> None:
        topic_dir = self._build_corrupted_topic(tmp_path)
        before_superseded = sum(
            1 for e in load_topic_entries(topic_dir) if e.status == "superseded"
        )

        plan = plan_topic_repair(topic_dir, topic="dependencies")
        apply_repair_plan(plan)

        after_superseded = sum(
            1 for e in load_topic_entries(topic_dir) if e.status == "superseded"
        )
        assert after_superseded == before_superseded == len(_OLD_TOPICS)
