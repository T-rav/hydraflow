"""Regression guard for #10757 — the #10655 N-to-1 merge content-completeness
check must actually exist.

#10655 asked for a completeness check that flags predecessors in a genuine
N-to-1 supersession merge whose *content* has no discernible representation in
the successor's body. PR #10693 closed #10655 with an unrelated ``fixed_in_pr``
dedup fix; the check itself never shipped (#10757). The supersession planner
records pointer moves, not content survival — so a merge could paraphrase away
every predecessor lesson but the title-matched one and still look healthy.

This guard reproduces the canonical case (``gotchas/0841``'s ``_SHA_MARKER``
lesson, PR #10521): a ``left_on_primary`` predecessor whose live code anchor
has no representation in the successor it was merged into. Before the fix,
nothing tiered it; the guard asserts the completeness check now classifies it
``orphaned`` — and, critically, that a merge which *does* carry the lesson
forward is NOT flagged (no false positive).
"""

from __future__ import annotations

from pathlib import Path

from wiki_lesson_coverage import assess_topic_coverage
from wiki_supersession_repair import plan_topic_repair


def _write_entry(
    topic_dir: Path,
    *,
    entry_id: str,
    title: str,
    body: str,
    status: str,
    superseded_by: str | None = None,
    supersedes: list[str] | None = None,
    code_refs: str | None = None,
) -> None:
    topic_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {entry_id}",
        "topic: gotchas",
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
    lines += ["---", "", f"# {title}", "", body, ""]
    slug = title.lower().replace(" ", "-")[:40]
    (topic_dir / f"{entry_id}-issue-synthesis-{slug}.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _build_corpus(tmp_path: Path, *, successor_body: str) -> tuple[Path, Path]:
    """A round where 0841 has no title match (left_on_primary) but 0842 does."""
    repo_root = tmp_path / "src_root"
    (repo_root / "src" / "escape").mkdir(parents=True)
    (repo_root / "src" / "escape" / "detect.py").write_text(
        '_SHA_MARKER = "\\x01ESCSHA\\x01"\n', encoding="utf-8"
    )
    topic_dir = tmp_path / "repo_wiki" / "T-rav" / "hydraflow" / "gotchas"
    _write_entry(
        topic_dir,
        entry_id="0841",
        title="str.splitlines breaks C0-separator markers in git log",
        body="Keep control-separator markers off characters str.splitlines "
        "treats as boundaries. See `src/escape/detect.py:_SHA_MARKER`.",
        status="superseded",
        superseded_by="0851",
        code_refs="src/escape/detect.py:_SHA_MARKER",
    )
    _write_entry(
        topic_dir,
        entry_id="0842",
        title="Clear hitl-escalation only alongside diagnose-failed",
        body="Require both labels before clearing.",
        status="superseded",
        superseded_by="0851",
    )
    _write_entry(
        topic_dir,
        entry_id="0851",
        title="Clear hitl-escalation only alongside diagnose-failed",
        body=successor_body,
        status="active",
        supersedes=["0841", "0842"],
    )
    return topic_dir, repo_root


def test_left_on_primary_predecessor_with_dropped_content_is_flagged_orphaned(
    tmp_path: Path,
) -> None:
    # Successor carries only 0842's (title-matched) lesson; 0841's marker lesson
    # is dropped — present only as a dangling wikilink pointer, which must not
    # count as representation.
    topic_dir, repo_root = _build_corpus(
        tmp_path,
        successor_body="Require both labels before clearing. For the marker "
        "rule see [[git_log_marker_splitlines_gotcha]].",
    )
    plan = plan_topic_repair(topic_dir, topic="gotchas")
    # 0841 is a genuine N-to-1 merge with no title match.
    assert any(
        r.entry_id == "0841" and r.reason == "left_on_primary" for r in plan.repoints
    )

    report = assess_topic_coverage(plan, topic_dir, repo_root)
    orphaned_ids = {v.predecessor_id for v in report.orphaned()}
    assert "0841" in orphaned_ids
    verdict = next(v for v in report.verdicts if v.predecessor_id == "0841")
    assert verdict.tier == "orphaned"
    assert verdict.live_anchors == ("_SHA_MARKER",)


def test_merge_that_carries_the_lesson_forward_is_not_flagged(tmp_path: Path) -> None:
    # No false positive: the successor DOES discuss the marker.
    topic_dir, repo_root = _build_corpus(
        tmp_path,
        successor_body="Require both labels before clearing. Also keep "
        "`_SHA_MARKER` off str.splitlines boundary chars when parsing git log.",
    )
    plan = plan_topic_repair(topic_dir, topic="gotchas")
    report = assess_topic_coverage(plan, topic_dir, repo_root)
    assert report.orphaned() == []
    verdict = next(v for v in report.verdicts if v.predecessor_id == "0841")
    assert verdict.tier == "represented"
