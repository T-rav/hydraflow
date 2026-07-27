"""Unit tests for the wiki supersession repair planner/applier (issue #10572).

Fixtures build tracked-layout entry files directly under ``tmp_path`` — never
the live ``repo_wiki/`` tree — mirroring the frontmatter shape
``repo_wiki._write_tracked_synthesis_entry`` / ``_mark_tracked_entry_superseded``
produce.
"""

from __future__ import annotations

from pathlib import Path

from wiki_supersession_repair import (
    apply_repair_plan,
    discover_topics,
    load_topic_entries,
    plan_topic_repair,
    summarize_plan,
)


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
        "topic: testing",
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
    slug = title.lower().replace(" ", "-")
    path = topic_dir / f"{entry_id}-issue-synthesis-{slug}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestTitleMatchedRepoint:
    """A round where every successor has a same-titled predecessor."""

    def test_each_predecessor_repoints_to_its_own_title_match(
        self, tmp_path: Path
    ) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(
            topic_dir,
            entry_id="0001",
            title="Alpha rule",
            status="superseded",
            superseded_by="0004",
        )
        _write_entry(
            topic_dir,
            entry_id="0002",
            title="Beta rule",
            status="superseded",
            superseded_by="0004",
        )
        _write_entry(
            topic_dir,
            entry_id="0003",
            title="Gamma rule",
            status="superseded",
            superseded_by="0004",
        )
        _write_entry(
            topic_dir,
            entry_id="0004",
            title="Alpha rule",
            supersedes=["0001", "0002", "0003"],
        )
        _write_entry(
            topic_dir,
            entry_id="0005",
            title="Beta rule",
            supersedes=["0001", "0002", "0003"],
        )
        _write_entry(
            topic_dir,
            entry_id="0006",
            title="Gamma rule",
            supersedes=["0001", "0002", "0003"],
        )

        plan = plan_topic_repair(topic_dir, topic="testing")

        by_id = {r.entry_id: r for r in plan.repoints}
        assert by_id["0001"].new_target == "0004"
        assert by_id["0001"].reason == "matched"
        assert by_id["0002"].new_target == "0005"
        assert by_id["0002"].reason == "matched"
        assert by_id["0003"].new_target == "0006"
        assert by_id["0003"].reason == "matched"

        rewrites_by_id = {r.entry_id: r for r in plan.rewrites}
        assert rewrites_by_id["0004"].new_ids == ("0001",)
        assert rewrites_by_id["0005"].new_ids == ("0002",)
        assert rewrites_by_id["0006"].new_ids == ("0003",)

    def test_union_across_round_equals_original_list(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(
            topic_dir,
            entry_id="0001",
            title="Alpha rule",
            status="superseded",
            superseded_by="0002",
        )
        _write_entry(
            topic_dir, entry_id="0002", title="Alpha rule", supersedes=["0001"]
        )

        plan = plan_topic_repair(topic_dir, topic="testing")

        original_union = {"0001"}
        new_union: set[str] = set()
        for rewrite in plan.rewrites:
            new_union.update(rewrite.new_ids)
        assert new_union == original_union


class TestNoTitleMatchLeftOnPrimary:
    def test_predecessor_with_no_title_match_keeps_existing_pointer(
        self, tmp_path: Path
    ) -> None:
        topic_dir = tmp_path / "testing"
        # 0001 has no title match among the round's successors (0004, 0005) —
        # a genuine N-to-1 merge into the primary (0004).
        _write_entry(
            topic_dir,
            entry_id="0001",
            title="Unrelated old topic",
            status="superseded",
            superseded_by="0004",
        )
        _write_entry(
            topic_dir,
            entry_id="0002",
            title="Beta rule",
            status="superseded",
            superseded_by="0004",
        )
        _write_entry(
            topic_dir,
            entry_id="0004",
            title="Merged summary",
            supersedes=["0001", "0002"],
        )
        _write_entry(
            topic_dir, entry_id="0005", title="Beta rule", supersedes=["0001", "0002"]
        )

        plan = plan_topic_repair(topic_dir, topic="testing")

        by_id = {r.entry_id: r for r in plan.repoints}
        assert by_id["0001"].reason == "left_on_primary"
        assert by_id["0001"].new_target == "0004"
        assert not by_id["0001"].changed

        assert by_id["0002"].reason == "matched"
        assert by_id["0002"].new_target == "0005"

        rewrites_by_id = {r.entry_id: r for r in plan.rewrites}
        # 0001 stays claimed by the primary; 0005 is trimmed to just 0002.
        assert rewrites_by_id["0004"].new_ids == ("0001",)
        assert rewrites_by_id["0005"].new_ids == ("0002",)


class TestAmbiguousTitleMatch:
    def test_two_same_titled_successors_leaves_pointer_and_reports_ambiguous(
        self, tmp_path: Path
    ) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(
            topic_dir,
            entry_id="0001",
            title="Dup rule",
            status="superseded",
            superseded_by="0002",
        )
        _write_entry(topic_dir, entry_id="0002", title="Dup rule", supersedes=["0001"])
        _write_entry(topic_dir, entry_id="0003", title="Dup rule", supersedes=["0001"])

        plan = plan_topic_repair(topic_dir, topic="testing")

        by_id = {r.entry_id: r for r in plan.repoints}
        assert by_id["0001"].reason == "ambiguous"
        assert by_id["0001"].new_target == "0002"
        assert not by_id["0001"].changed


class TestUnclaimedEntry:
    def test_entry_named_by_no_successor_is_reported_not_modified(
        self, tmp_path: Path
    ) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(
            topic_dir,
            entry_id="0001",
            title="Orphan rule",
            status="superseded",
            superseded_by="0002",
        )
        _write_entry(topic_dir, entry_id="0002", title="Some other rule")

        plan = plan_topic_repair(topic_dir, topic="testing")

        by_id = {r.entry_id: r for r in plan.repoints}
        assert by_id["0001"].reason == "unclaimed"
        assert not by_id["0001"].changed
        assert plan.rewrites == []


class TestNonSupersededEntriesUntouched:
    def test_active_entries_are_never_repointed(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(topic_dir, entry_id="0001", title="Still active")
        _write_entry(topic_dir, entry_id="0002", title="Successor", supersedes=["0001"])

        plan = plan_topic_repair(topic_dir, topic="testing")

        assert plan.repoints == []


class TestApply:
    def test_apply_rewrites_only_frontmatter_fields(self, tmp_path: Path) -> None:
        # 0001's cartesian superseded_by points at 0002 (wrong title), but
        # its true title match is 0003 (already correctly listing 0001 in
        # its own supersedes) — exercises a repoint plus a trim-to-empty on
        # the wrongly-targeted sibling, in one apply() call.
        topic_dir = tmp_path / "testing"
        pred_path = _write_entry(
            topic_dir,
            entry_id="0001",
            title="Alpha rule",
            status="superseded",
            superseded_by="0002",
        )
        succ_wrong_path = _write_entry(
            topic_dir, entry_id="0002", title="Beta rule", supersedes=["0001"]
        )
        succ_right_path = _write_entry(
            topic_dir, entry_id="0003", title="Alpha rule", supersedes=["0001"]
        )

        before_pred_body = _read(pred_path).split("\n---\n", 1)[1]
        before_succ_right_fields = _read(succ_right_path).split("\n---\n", 1)[0]

        plan = plan_topic_repair(topic_dir, topic="testing")
        touched = apply_repair_plan(plan)
        assert (
            touched == 2
        )  # 0001 repointed to 0003; 0002 trimmed to empty; 0003 unchanged

        after_pred_text = _read(pred_path)
        assert "superseded_by: 0003" in after_pred_text
        assert (
            after_pred_text.split("\n---\n", 1)[1] == before_pred_body
        )  # body untouched

        after_succ_wrong_text = _read(succ_wrong_path)
        assert (
            "supersedes:" not in after_succ_wrong_text
        )  # trimmed to empty -> field dropped

        after_succ_right_text = _read(succ_right_path)
        assert "supersedes: 0001" in after_succ_right_text
        # Every other frontmatter key on the correctly-matched successor is untouched.
        for line in before_succ_right_fields.strip().splitlines():
            if line.split(":", 1)[0].strip() == "supersedes":
                continue
            assert line in after_succ_right_text

    def test_dry_run_plan_alone_writes_nothing(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "testing"
        path = _write_entry(
            topic_dir,
            entry_id="0001",
            title="Alpha rule",
            status="superseded",
            superseded_by="0002",
        )
        _write_entry(
            topic_dir, entry_id="0002", title="Alpha rule", supersedes=["0001"]
        )

        before = _read(path)
        plan_topic_repair(topic_dir, topic="testing")
        after = _read(path)

        assert before == after


class TestIdempotency:
    def test_second_apply_reports_zero_changes(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(
            topic_dir,
            entry_id="0001",
            title="Alpha rule",
            status="superseded",
            superseded_by="0004",
        )
        _write_entry(
            topic_dir,
            entry_id="0002",
            title="Beta rule",
            status="superseded",
            superseded_by="0004",
        )
        _write_entry(
            topic_dir, entry_id="0004", title="Alpha rule", supersedes=["0001", "0002"]
        )
        _write_entry(
            topic_dir, entry_id="0005", title="Beta rule", supersedes=["0001", "0002"]
        )

        first_plan = plan_topic_repair(topic_dir, topic="testing")
        first_touched = apply_repair_plan(first_plan)
        assert first_touched > 0

        second_plan = plan_topic_repair(topic_dir, topic="testing")
        assert second_plan.changed_repoints == []
        assert second_plan.changed_rewrites == []
        second_touched = apply_repair_plan(second_plan)
        assert second_touched == 0

    def test_already_repaired_topic_yields_zero_changes(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(
            topic_dir,
            entry_id="0001",
            title="Alpha rule",
            status="superseded",
            superseded_by="0002",
        )
        _write_entry(
            topic_dir, entry_id="0002", title="Alpha rule", supersedes=["0001"]
        )

        plan = plan_topic_repair(topic_dir, topic="testing")

        assert plan.changed_repoints == []
        assert plan.changed_rewrites == []


class TestDiscoverTopics:
    def test_scans_directory_without_a_hardcoded_list(self, tmp_path: Path) -> None:
        tracked_root = tmp_path / "repo_wiki"
        (tracked_root / "acme/widget" / "testing").mkdir(parents=True)
        (tracked_root / "acme/widget" / "gotchas").mkdir(parents=True)

        assert discover_topics(tracked_root, "acme/widget") == ["gotchas", "testing"]

        # A brand-new topic dir is picked up with no code change.
        (tracked_root / "acme/widget" / "brand-new-topic").mkdir(parents=True)
        assert discover_topics(tracked_root, "acme/widget") == [
            "brand-new-topic",
            "gotchas",
            "testing",
        ]

    def test_missing_repo_dir_returns_empty(self, tmp_path: Path) -> None:
        assert discover_topics(tmp_path / "repo_wiki", "nope/nope") == []


class TestSummarizePlan:
    def test_counts_match_reasons(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(
            topic_dir,
            entry_id="0001",
            title="Alpha rule",
            status="superseded",
            superseded_by="0002",
        )
        _write_entry(
            topic_dir, entry_id="0002", title="Alpha rule", supersedes=["0001"]
        )
        _write_entry(
            topic_dir,
            entry_id="0003",
            title="Orphan",
            status="superseded",
            superseded_by="0099",
        )

        plan = plan_topic_repair(topic_dir, topic="testing")
        report = summarize_plan(plan)

        assert report.topic == "testing"
        assert report.total_superseded == 2
        assert report.matched == 1
        assert report.unclaimed == 1
        assert report.left_on_primary == 0
        assert report.ambiguous == 0


class TestLoadTopicEntries:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert load_topic_entries(tmp_path / "does-not-exist") == []

    def test_loads_both_active_and_superseded(self, tmp_path: Path) -> None:
        topic_dir = tmp_path / "testing"
        _write_entry(topic_dir, entry_id="0001", title="Active one")
        _write_entry(
            topic_dir,
            entry_id="0002",
            title="Superseded one",
            status="superseded",
            superseded_by="0001",
        )

        entries = load_topic_entries(topic_dir)

        statuses = {e.id: e.status for e in entries}
        assert statuses == {"0001": "active", "0002": "superseded"}
