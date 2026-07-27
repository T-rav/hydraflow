"""Regression pins for P1 of epic #10682 — wiki-compilation on the flow primitive.

``WikiCompiler.compile_topic_tracked`` is a structural refactor onto the P0
``src/flows`` DAG runtime (ADR-0111): the same multi-step compile, now expressed
as explicit ``Node``/``Edge`` graph instead of a straight-line method. These
tests pin the load-bearing invariants of that cutover:

1. **Node order.** The flow walks ``extract -> verify -> synthesize -> validate``
   (then a terminal ``done``) — the documented direction of the compile.
2. **Output parity.** The public entry (now flow-backed) produces byte-identical
   on-disk output to the pre-refactor path for a seeded topic: one synthesis
   entry, the ``supersedes`` pointer, every input flipped to ``superseded``.
3. **LLM stays inside a node.** The model call lives in ``synthesize`` only, so a
   topic with < 2 active entries short-circuits in ``extract`` and never spends a
   model call.
4. **Fail-closed.** A ``None`` model result aborts before ``validate`` — nothing
   is written, inputs stay ``active`` (ADR-0049).
5. **Checkpoint seam.** The injectable ``checkpoint`` hook fires once per node in
   walk order via the JSONL adapter — the resume substrate the later phase
   conversions (P2/P3) depend on.

Parity is the safety net for this no-flag refactor; if any of these regress a
converted phase could resume mid-node, drop a step, or silently change the
maintenance-PR output.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from flows import Flow, jsonl_checkpoint
from wiki_compiler import WikiCompiler

REPO = "acme/widget"

# Anchored synthesis output (names RepoWikiLoop / src/repo_wiki.py) so the #9954
# repo-anchor gate keeps it rather than dropping it as a generic platitude.
_ANCHORED_OUTPUT = (
    '[{"title":"Merged","content":"RepoWikiLoop unifies these. '
    'See `src/repo_wiki.py`.","source_type":"synthesis"}]'
)


def _write_entry_file(
    path: Path,
    *,
    entry_id: str,
    topic: str,
    status: str = "active",
    source_issue: int = 1,
    title: str = "Existing entry",
    body: str = "Content body.",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: plan\n"
        f"created_at: {now}\n"
        f"status: {status}\n"
        "---\n"
        "\n"
        f"# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def _make_compiler() -> WikiCompiler:
    """A WikiCompiler with a mocked config/runner (no real LLM backend)."""
    compiler = WikiCompiler.__new__(WikiCompiler)
    compiler._config = MagicMock()
    compiler._config.wiki_compilation_tool = "stub"
    compiler._config.wiki_compilation_model = "stub"
    compiler._config.wiki_compilation_timeout = 60
    compiler._credentials = MagicMock()
    compiler._credentials.gh_token = ""
    compiler._runner = MagicMock()
    return compiler


@pytest.fixture
def compiler_with_three_active(tmp_path: Path) -> tuple[WikiCompiler, Path]:
    tracked_root = tmp_path / "repo_wiki"
    topic_dir = tracked_root / REPO / "patterns"
    for i in range(3):
        _write_entry_file(
            topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md",
            entry_id=f"000{i + 1}",
            topic="patterns",
            source_issue=i + 1,
            title=f"Original {i + 1}",
        )
    return _make_compiler(), tracked_root


def _initial_state(tracked_root: Path) -> dict:
    return {
        "tracked_root": tracked_root,
        "repo": REPO,
        "topic": "patterns",
        "other_topics": None,
        "result": 0,
    }


async def test_compile_runs_on_the_flow_primitive(
    compiler_with_three_active: tuple[WikiCompiler, Path],
) -> None:
    """The public compile builds an ``src.flows.Flow`` whose entry is ``extract``."""
    compiler, _ = compiler_with_three_active

    flow = compiler._build_compile_flow()

    assert isinstance(flow, Flow)
    assert flow.entry == "extract"


async def test_nodes_execute_in_extract_verify_synthesize_validate_order(
    compiler_with_three_active: tuple[WikiCompiler, Path],
) -> None:
    """Happy path walks extract -> verify -> synthesize -> validate -> done."""
    compiler, tracked_root = compiler_with_three_active
    compiler._call_model = AsyncMock(return_value=_ANCHORED_OUTPUT)

    recorded: list[str] = []
    flow = compiler._build_compile_flow(
        checkpoint=lambda name, _state: recorded.append(name)
    )
    result = await flow.run(_initial_state(tracked_root))

    assert result.path[:4] == ["extract", "verify", "synthesize", "validate"]
    assert result.terminal == "done"
    # Checkpoint fires once per node, in walk order.
    assert recorded == ["extract", "verify", "synthesize", "validate", "done"]
    assert result.state["result"] == 1


async def test_public_entry_output_parity_via_flow(
    compiler_with_three_active: tuple[WikiCompiler, Path],
) -> None:
    """Flow-backed public entry writes the same synthesis + supersession output."""
    compiler, tracked_root = compiler_with_three_active
    compiler._call_model = AsyncMock(return_value=_ANCHORED_OUTPUT)

    count = await compiler.compile_topic_tracked(tracked_root, REPO, "patterns")

    assert count == 1
    topic_dir = tracked_root / REPO / "patterns"
    synthesis = list(topic_dir.glob("*-issue-synthesis-*.md"))
    assert len(synthesis) == 1
    synth_text = synthesis[0].read_text()
    assert "supersedes: 0001,0002,0003" in synth_text
    for i in range(3):
        original = topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md"
        assert "status: superseded" in original.read_text()


async def test_fewer_than_two_active_short_circuits_before_model(
    tmp_path: Path,
) -> None:
    """< 2 active entries aborts in ``extract`` — the model node never runs."""
    tracked_root = tmp_path / "repo_wiki"
    topic_dir = tracked_root / REPO / "patterns"
    _write_entry_file(
        topic_dir / "0001-issue-1-solo.md",
        entry_id="0001",
        topic="patterns",
        title="Solo",
    )
    compiler = _make_compiler()
    compiler._call_model = AsyncMock(
        side_effect=AssertionError("model must not be called")
    )

    count = await compiler.compile_topic_tracked(tracked_root, REPO, "patterns")

    assert count == 0
    compiler._call_model.assert_not_awaited()
    assert "status: active" in (topic_dir / "0001-issue-1-solo.md").read_text()


async def test_model_failure_fails_closed_without_writing(
    compiler_with_three_active: tuple[WikiCompiler, Path],
) -> None:
    """A ``None`` model result aborts before ``validate`` — nothing is written."""
    compiler, tracked_root = compiler_with_three_active
    compiler._call_model = AsyncMock(return_value=None)

    count = await compiler.compile_topic_tracked(tracked_root, REPO, "patterns")

    assert count == 0
    topic_dir = tracked_root / REPO / "patterns"
    assert list(topic_dir.glob("*-issue-synthesis-*.md")) == []
    for i in range(3):
        assert (
            "status: active"
            in (topic_dir / f"000{i + 1}-issue-{i + 1}-orig.md").read_text()
        )


async def test_checkpoint_seam_records_one_jsonl_line_per_node(
    compiler_with_three_active: tuple[WikiCompiler, Path],
    tmp_path: Path,
) -> None:
    """The JSONL checkpoint adapter appends one crash-safe record per node."""
    compiler, tracked_root = compiler_with_three_active
    compiler._call_model = AsyncMock(return_value=_ANCHORED_OUTPUT)

    ckpt = tmp_path / "wiki_flow.jsonl"
    flow = compiler._build_compile_flow(checkpoint=jsonl_checkpoint(ckpt))
    await flow.run(_initial_state(tracked_root))

    records = [json.loads(line) for line in ckpt.read_text().splitlines()]
    assert [r["node"] for r in records] == [
        "extract",
        "verify",
        "synthesize",
        "validate",
        "done",
    ]
