"""Unit tests for the N-to-1 wiki-merge lesson-coverage auditor (#10757/#10655).

The auditor tiers each ``left_on_primary`` predecessor (a genuine N-to-1
merge, per ``wiki_supersession_repair.plan_topic_repair``) by *lesson
survival*: does the predecessor's live code anchor still appear in the live
terminal successor's body?

Fixtures build tracked-layout entry files + a throwaway ``src/`` tree under
``tmp_path`` — never the live ``repo_wiki/`` tree — so anchor liveness is
resolved against a controlled, in-test codebase.
"""

from __future__ import annotations

from pathlib import Path

from wiki_lesson_coverage import (
    Anchor,
    SymbolIndex,
    assess_predecessor_coverage,
    assess_repo_coverage,
    assess_topic_coverage,
    entry_anchors,
    resolve_terminal,
    strip_wikilinks,
)
from wiki_supersession_repair import TrackedFile, plan_topic_repair

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_entry(
    topic_dir: Path,
    *,
    entry_id: str,
    title: str,
    body: str = "",
    status: str = "active",
    superseded_by: str | None = None,
    supersedes: list[str] | None = None,
    code_refs: str | None = None,
) -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {entry_id}",
        f"topic: {topic_dir.name}",
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
    if code_refs is not None:
        lines.append(f"code_refs: {code_refs}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(body or f"Body content for {entry_id}.")
    lines.append("")
    slug = title.lower().replace(" ", "-")
    path = topic_dir / f"{entry_id}-issue-synthesis-{slug}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _tracked(
    *,
    entry_id: str,
    title: str,
    body: str = "",
    status: str = "active",
    superseded_by: str | None = None,
    code_refs: str | None = None,
) -> TrackedFile:
    fields: dict[str, str] = {"id": entry_id, "status": status}
    if superseded_by is not None:
        fields["superseded_by"] = superseded_by
    if code_refs is not None:
        fields["code_refs"] = code_refs
    return TrackedFile(
        id=entry_id,
        title=title,
        status=status,
        superseded_by=superseded_by,
        supersedes=(),
        path=Path(f"{entry_id}.md"),
        fields=fields,
        body=body,
    )


def _write_live_symbol(repo_root: Path, module_path: str, symbol: str) -> None:
    """Materialise a module under *repo_root* that defines *symbol*."""
    target = repo_root / module_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'{symbol} = "live"\n', encoding="utf-8")


# ---------------------------------------------------------------------------
# strip_wikilinks
# ---------------------------------------------------------------------------


class TestStripWikilinks:
    def test_removes_wikilink_target_text(self) -> None:
        out = strip_wikilinks("see [[git_log_marker_splitlines_gotcha]] for detail")
        assert "git_log_marker_splitlines_gotcha" not in out

    def test_keeps_ordinary_prose(self) -> None:
        assert "keep this" in strip_wikilinks("keep this [[dropme]] text")


# ---------------------------------------------------------------------------
# entry_anchors
# ---------------------------------------------------------------------------


class TestEntryAnchors:
    def test_extracts_symbol_from_code_refs_frontmatter(self) -> None:
        entry = _tracked(
            entry_id="0841",
            title="marker bug",
            code_refs="src/escape/detect.py:_SHA_MARKER,src/audit/detect.py:_SHA_MARKER",
        )
        anchors = entry_anchors(entry)
        symbols = {a.symbol for a in anchors}
        assert symbols == {"_SHA_MARKER"}
        modules = {a.module_path for a in anchors}
        assert "src/escape/detect.py" in modules
        assert "src/audit/detect.py" in modules

    def test_extracts_style_a_cites_from_body(self) -> None:
        entry = _tracked(
            entry_id="0001",
            title="body cite",
            body="The fix lives in `src/foo.py:do_thing` now.",
        )
        anchors = entry_anchors(entry)
        assert (
            Anchor(
                module_path="src/foo.py", symbol="do_thing", raw="src/foo.py:do_thing"
            )
            in anchors
        )

    def test_no_anchors_when_no_refs_or_cites(self) -> None:
        entry = _tracked(entry_id="0002", title="prose only", body="Just prose here.")
        assert entry_anchors(entry) == []


# ---------------------------------------------------------------------------
# SymbolIndex
# ---------------------------------------------------------------------------


class TestSymbolIndex:
    def test_resolves_live_module_level_constant(self, tmp_path: Path) -> None:
        _write_live_symbol(tmp_path, "src/escape/detect.py", "_SHA_MARKER")
        index = SymbolIndex(tmp_path)
        assert (
            index.resolves(Anchor("src/escape/detect.py", "_SHA_MARKER", "x")) is True
        )

    def test_missing_symbol_does_not_resolve(self, tmp_path: Path) -> None:
        _write_live_symbol(tmp_path, "src/escape/detect.py", "_OTHER")
        index = SymbolIndex(tmp_path)
        assert (
            index.resolves(Anchor("src/escape/detect.py", "_SHA_MARKER", "x")) is False
        )

    def test_missing_module_does_not_resolve(self, tmp_path: Path) -> None:
        index = SymbolIndex(tmp_path)
        assert index.resolves(Anchor("src/gone.py", "thing", "x")) is False


# ---------------------------------------------------------------------------
# resolve_terminal
# ---------------------------------------------------------------------------


class TestResolveTerminal:
    def test_follows_chain_to_active_terminal(self) -> None:
        a = _tracked(entry_id="A", title="a", status="superseded", superseded_by="B")
        b = _tracked(entry_id="B", title="b", status="superseded", superseded_by="C")
        c = _tracked(entry_id="C", title="c", status="active")
        by_id = {"A": a, "B": b, "C": c}
        assert resolve_terminal(a, by_id).id == "C"

    def test_stops_when_target_missing(self) -> None:
        a = _tracked(entry_id="A", title="a", status="superseded", superseded_by="Z")
        by_id = {"A": a}
        assert resolve_terminal(a, by_id).id == "A"

    def test_cycle_is_safe(self) -> None:
        a = _tracked(entry_id="A", title="a", status="superseded", superseded_by="B")
        b = _tracked(entry_id="B", title="b", status="superseded", superseded_by="A")
        by_id = {"A": a, "B": b}
        # Must terminate, not loop forever.
        assert resolve_terminal(a, by_id).id in {"A", "B"}


# ---------------------------------------------------------------------------
# assess_predecessor_coverage — the tiering core
# ---------------------------------------------------------------------------


class TestPredecessorTiering:
    def test_orphaned_when_live_anchor_absent_from_terminal(
        self, tmp_path: Path
    ) -> None:
        _write_live_symbol(tmp_path, "src/escape/detect.py", "_SHA_MARKER")
        index = SymbolIndex(tmp_path)
        pred = _tracked(
            entry_id="0841",
            title="marker bug",
            code_refs="src/escape/detect.py:_SHA_MARKER",
        )
        terminal = _tracked(
            entry_id="0851",
            title="unrelated hitl lesson",
            body="Clear hitl-escalation label only alongside diagnose-failed.",
        )
        verdict = assess_predecessor_coverage(pred, terminal, index, topic="gotchas")
        assert verdict.tier == "orphaned"
        assert verdict.live_anchors == ("_SHA_MARKER",)
        assert verdict.surviving_anchors == ()

    def test_represented_when_all_live_anchors_survive(self, tmp_path: Path) -> None:
        _write_live_symbol(tmp_path, "src/escape/detect.py", "_SHA_MARKER")
        index = SymbolIndex(tmp_path)
        pred = _tracked(
            entry_id="0841",
            title="marker bug",
            code_refs="src/escape/detect.py:_SHA_MARKER",
        )
        terminal = _tracked(
            entry_id="0851",
            title="successor",
            body="The successor still discusses `_SHA_MARKER` and its parse.",
        )
        verdict = assess_predecessor_coverage(pred, terminal, index, topic="gotchas")
        assert verdict.tier == "represented"
        assert verdict.containment == 1.0

    def test_weak_when_some_anchors_survive(self, tmp_path: Path) -> None:
        _write_live_symbol(tmp_path, "src/a.py", "alpha")
        _write_live_symbol(tmp_path, "src/b.py", "beta")
        index = SymbolIndex(tmp_path)
        pred = _tracked(
            entry_id="0001",
            title="two anchors",
            code_refs="src/a.py:alpha,src/b.py:beta",
        )
        terminal = _tracked(
            entry_id="0002",
            title="successor",
            body="Only alpha is carried forward here.",
        )
        verdict = assess_predecessor_coverage(pred, terminal, index, topic="gotchas")
        assert verdict.tier == "weak"
        assert 0.0 < verdict.containment < 1.0

    def test_not_live_when_no_anchor_resolves(self, tmp_path: Path) -> None:
        index = SymbolIndex(tmp_path)  # empty repo — nothing resolves
        pred = _tracked(
            entry_id="0001",
            title="dangling",
            code_refs="src/gone.py:vanished",
        )
        terminal = _tracked(entry_id="0002", title="successor", body="anything")
        verdict = assess_predecessor_coverage(pred, terminal, index, topic="gotchas")
        assert verdict.tier == "not_live"

    def test_no_anchor_when_predecessor_cites_nothing(self, tmp_path: Path) -> None:
        index = SymbolIndex(tmp_path)
        pred = _tracked(entry_id="0001", title="prose", body="Just a prose lesson.")
        terminal = _tracked(entry_id="0002", title="successor", body="anything")
        verdict = assess_predecessor_coverage(pred, terminal, index, topic="gotchas")
        assert verdict.tier == "no_anchor"

    def test_wikilink_pointer_does_not_count_as_representation(
        self, tmp_path: Path
    ) -> None:
        _write_live_symbol(tmp_path, "src/escape/detect.py", "_SHA_MARKER")
        index = SymbolIndex(tmp_path)
        pred = _tracked(
            entry_id="0841",
            title="marker bug",
            code_refs="src/escape/detect.py:_SHA_MARKER",
        )
        # Terminal carries the lesson only as a dangling wikilink pointer.
        terminal = _tracked(
            entry_id="0851",
            title="successor",
            body="For the marker rule see [[_SHA_MARKER]].",
        )
        verdict = assess_predecessor_coverage(pred, terminal, index, topic="gotchas")
        assert verdict.tier == "orphaned"


# ---------------------------------------------------------------------------
# assess_topic_coverage — reads plan.repoints, tiers only left_on_primary
# ---------------------------------------------------------------------------


class TestTopicCoverage:
    def test_only_left_on_primary_predecessors_are_tiered(self, tmp_path: Path) -> None:
        _write_live_symbol(tmp_path, "src/escape/detect.py", "_SHA_MARKER")
        topic_dir = tmp_path / "repo_wiki" / "T-rav" / "hydraflow" / "gotchas"

        # left_on_primary predecessor: no title-matched sibling in its round.
        _write_entry(
            topic_dir,
            entry_id="0841",
            title="Marker splitlines bug",
            status="superseded",
            superseded_by="0851",
            code_refs="src/escape/detect.py:_SHA_MARKER",
        )
        # matched predecessor: shares its H1 title with its successor.
        _write_entry(
            topic_dir,
            entry_id="0842",
            title="Beta rule",
            status="superseded",
            superseded_by="0851",
        )
        _write_entry(
            topic_dir,
            entry_id="0851",
            title="Beta rule",
            status="active",
            supersedes=["0841", "0842"],
            body="Beta rule body — no marker mention.",
        )

        plan = plan_topic_repair(topic_dir, topic="gotchas")
        report = assess_topic_coverage(plan, topic_dir, tmp_path)

        tiered_ids = {v.predecessor_id for v in report.verdicts}
        assert tiered_ids == {"0841"}  # only the left_on_primary one
        assert report.verdicts[0].tier == "orphaned"

    def test_tier_counts_aggregate(self, tmp_path: Path) -> None:
        _write_live_symbol(tmp_path, "src/escape/detect.py", "_SHA_MARKER")
        topic_dir = tmp_path / "repo_wiki" / "T-rav" / "hydraflow" / "gotchas"
        _write_entry(
            topic_dir,
            entry_id="0841",
            title="Marker splitlines bug",
            status="superseded",
            superseded_by="0851",
            code_refs="src/escape/detect.py:_SHA_MARKER",
        )
        _write_entry(
            topic_dir,
            entry_id="0851",
            title="Unrelated successor",
            status="active",
            supersedes=["0841"],
            body="Nothing about the marker here.",
        )
        plan = plan_topic_repair(topic_dir, topic="gotchas")
        report = assess_topic_coverage(plan, topic_dir, tmp_path)
        assert report.tier_counts.get("orphaned") == 1
        assert [v.predecessor_id for v in report.orphaned()] == ["0841"]


# ---------------------------------------------------------------------------
# assess_repo_coverage — corpus-wide, JSON-serialisable
# ---------------------------------------------------------------------------


class TestRepoCoverage:
    def test_aggregates_across_topics_and_serialises(self, tmp_path: Path) -> None:
        _write_live_symbol(tmp_path, "src/escape/detect.py", "_SHA_MARKER")
        tracked_root = tmp_path / "repo_wiki"
        gotchas = tracked_root / "T-rav" / "hydraflow" / "gotchas"
        _write_entry(
            gotchas,
            entry_id="0841",
            title="Marker splitlines bug",
            status="superseded",
            superseded_by="0851",
            code_refs="src/escape/detect.py:_SHA_MARKER",
        )
        _write_entry(
            gotchas,
            entry_id="0851",
            title="Unrelated successor",
            status="active",
            supersedes=["0841"],
            body="Nothing about the marker here.",
        )
        report = assess_repo_coverage(tracked_root, "T-rav/hydraflow", tmp_path)
        assert report.tier_counts.get("orphaned") == 1
        payload = report.to_dict()
        assert payload["repo"] == "T-rav/hydraflow"
        assert payload["tier_counts"]["orphaned"] == 1
        # Orphan verdicts carry enough to locate the dropped lesson.
        orphan = payload["orphaned"][0]
        assert orphan["predecessor_id"] == "0841"
        assert orphan["live_anchors"] == ["_SHA_MARKER"]
