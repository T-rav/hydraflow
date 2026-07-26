"""Regression: N-to-1 wiki supersession merges must preserve *every* source's
``fixed_in_pr`` reference on the successor — none silently dropped or mangled
(issue #10655).

``WikiCompiler.compile_topic_tracked`` unions the source entries'
shipped-claim provenance onto each synthesized entry
(``_union_shipped_claim_provenance``, the flow's ``verify``/``validate``
nodes, #10590). ``code_refs`` is unioned at *item* granularity — each ref
deduped individually — but ``fixed_in_pr`` was unioned as one opaque
whole-string token. A source's ``fixed_in_pr`` is frequently a
comma-joined *compound* of several PRs (any prior synthesis round emits
one — see #10590's own ``fixed_in_pr: #8713,#8720`` output). When such a
compound source is merged N-to-1 with a sibling that shares one of its
PRs, whole-string dedup never recognises the embedded PR as already
present: the shared reference is emitted twice and the individual PRs
inside the compound are never carried as first-class, distinct references.

The concrete #10655 case: ``gotchas/0841`` (the ``\\x1e`` marker fix,
PR #10521) merged alongside a compound sibling that already folded #10521
in. The union must land ``{#10521, #10566}`` on the successor, each PR
exactly once — not ``#10521,#10566,#10521,#10566``.

Fix: split each source ``fixed_in_pr`` on commas and union at
individual-PR granularity, symmetric with ``code_refs``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repo_wiki import _load_tracked_active_entries
from wiki_compiler import WikiCompiler

REPO = "acme/widget"


def _split_prs(raw: str | None) -> list[str]:
    """Split a serialized ``fixed_in_pr`` value into individual PR tokens."""
    if not raw:
        return []
    return [tok.strip() for tok in raw.split(",") if tok.strip()]


def _write_source_entry(
    path: Path,
    *,
    entry_id: str,
    topic: str,
    source_issue: str | int,
    title: str,
    body: str,
    fixed_in_pr: str | None = None,
    code_refs: tuple[str, ...] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    lines = [
        "---",
        f"id: {entry_id}",
        f"topic: {topic}",
        f"source_issue: {source_issue}",
        "source_phase: plan",
        f"created_at: {now}",
        "status: active",
        "corroborations: 1",
    ]
    if fixed_in_pr:
        lines.append(f"fixed_in_pr: {fixed_in_pr}")
    if code_refs:
        lines.append("code_refs: " + ",".join(code_refs))
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(body)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_compiler() -> WikiCompiler:
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._config = MagicMock()
    compiler._config.wiki_compilation_tool = "stub"
    compiler._config.wiki_compilation_model = "stub"
    compiler._config.wiki_compilation_timeout = 60
    compiler._credentials = MagicMock()
    compiler._credentials.gh_token = ""
    compiler._runner = MagicMock()
    return compiler


class TestUnionSplitsCompoundFixedInPr:
    """Unit: ``_union_shipped_claim_provenance`` unions PRs at PR granularity."""

    def test_compound_source_pr_not_duplicated_across_n_to_1_merge(self) -> None:
        # gotchas/0841 carries the \x1e marker fix (#10521); a compound
        # sibling already folded #10521 in alongside #10566; a third source
        # carries #10566 on its own — a genuine N-to-1 merge.
        sources = [
            {"id": "0841", "fixed_in_pr": "#10521", "code_refs": ()},
            {"id": "0842", "fixed_in_pr": "#10566,#10521", "code_refs": ()},
            {"id": "0844", "fixed_in_pr": "#10566", "code_refs": ()},
        ]

        union_pr, _ = WikiCompiler._union_shipped_claim_provenance(sources)

        prs = _split_prs(union_pr)
        # No source PR dropped.
        assert set(prs) == {"#10521", "#10566"}
        # No PR duplicated — each embedded PR is a distinct, once-listed ref.
        assert len(prs) == len(set(prs)), (
            f"compound-source PR duplicated in union: {union_pr!r}"
        )
        # Order-preserving: first appearance across sources wins.
        assert prs == ["#10521", "#10566"]

    def test_internal_duplicate_within_single_source_collapsed(self) -> None:
        sources = [{"id": "0001", "fixed_in_pr": "#77,#77", "code_refs": ()}]

        union_pr, _ = WikiCompiler._union_shipped_claim_provenance(sources)

        assert _split_prs(union_pr) == ["#77"]

    def test_none_when_no_source_carries_a_pr(self) -> None:
        sources = [
            {"id": "0001", "fixed_in_pr": None, "code_refs": ()},
            {"id": "0002", "fixed_in_pr": "", "code_refs": ()},
        ]

        union_pr, _ = WikiCompiler._union_shipped_claim_provenance(sources)

        assert union_pr is None


class TestCompileTopicTrackedNToOnePreservesEveryPr:
    """Integration: the full N-to-1 supersession keeps every PR exactly once."""

    @pytest.mark.asyncio
    async def test_successor_carries_each_source_pr_exactly_once(
        self, tmp_path: Path
    ) -> None:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "gotchas"
        _write_source_entry(
            topic_dir / "0841-issue-1-marker.md",
            entry_id="0841",
            topic="gotchas",
            source_issue=1,
            title="Marker splitlines gotcha",
            body="The `\\x1e` marker survives `str.splitlines()`.",
            fixed_in_pr="#10521",
        )
        _write_source_entry(
            topic_dir / "0842-issue-9-merged.md",
            entry_id="0842",
            topic="gotchas",
            source_issue=9,
            title="Cartesian supersession mapping",
            body="Topical supersession, not cartesian.",
            fixed_in_pr="#10566,#10521",
        )
        _write_source_entry(
            topic_dir / "0844-issue-2-scoping.md",
            entry_id="0844",
            topic="gotchas",
            source_issue=2,
            title="PR-scoping overlap",
            body="Overlapping root-cause PR scoping.",
            fixed_in_pr="#10566",
        )

        compiler = _make_compiler()
        # Single anchored, non-duplicate synthesis entry: a genuine N-to-1.
        compiler._call_model = AsyncMock(
            return_value='[{"title":"Marker + scoping gotcha","content":"One '
            'lesson. See `src/repo_wiki.py`.","source_type":"synthesis"}]'
        )

        count = await compiler.compile_topic_tracked(tracked_root, REPO, "gotchas")

        assert count == 1
        synthesis = list(topic_dir.glob("*-issue-synthesis-*.md"))
        assert len(synthesis) == 1
        text = synthesis[0].read_text()

        loaded = _load_tracked_active_entries(topic_dir)
        assert len(loaded) == 1
        prs = _split_prs(loaded[0]["fixed_in_pr"])
        # Every source PR survives (the \x1e marker's #10521 is not dropped).
        assert set(prs) == {"#10521", "#10566"}
        # Each PR is carried exactly once — no compound-source mangling.
        assert len(prs) == len(set(prs)), f"successor duplicated a PR ref: {text!r}"
