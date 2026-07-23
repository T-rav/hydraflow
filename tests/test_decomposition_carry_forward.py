"""Tests for decompose-to-converge carry-forward + salvage ordering (ADR-0105,
task 6).

Two behaviors under test, both required so decomposed children actually
converge instead of re-stalling as smaller clones of the parent:

1. **Carry-forward** -- every child ``IssueDecomposer.create_epic_from_result``
   creates embeds the parent's ``stall_context`` wrapped in an explicit
   "must not repeat that failure" line, so each child agent sees why the
   parent stalled and is told not to repeat it. Task 2 already proved *a*
   form of carry-forward existed (raw string append, see
   ``tests/test_issue_decomposer.py::test_stall_context_embedded_in_every_child_body``);
   this file pins the specific "Parent #<n> stalled on: ... must not repeat"
   phrasing this task adds on top of that.
2. **Salvage ordering** -- when the DecompositionCouncil's direction pass
   scopes one child as "land the already-working slice" (marked via a
   ``salvage`` label), ``IssueDecomposer`` creates that child FIRST, ahead
   of the riskier children, regardless of its position in
   ``EpicDecompResult.children``.

The LLM seam is always mocked in the council-level tests here -- they never
call a real model (mirrors ``tests/test_decomposition_council.py``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from decomposition_council import DecompositionCouncil
from issue_decomposer import IssueDecomposer
from mockworld.fakes.fake_github import FakeGitHub
from models import EpicDecompResult, NewIssueSpec
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_tracker


def _make_decomposer(tmp_path: Path):
    """Build an IssueDecomposer with a real FakeGitHub + StateTracker.

    Mirrors ``tests/test_issue_decomposer.py::_make_decomposer``.
    """
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    prs = FakeGitHub()
    epic_manager = MagicMock()
    epic_manager.register_epic = AsyncMock()
    state = make_tracker(tmp_path)
    decomposer = IssueDecomposer(prs, epic_manager, state, config)
    return decomposer, prs, epic_manager, state, config


def _two_child_result(**overrides: object) -> EpicDecompResult:
    defaults: dict[str, object] = {
        "should_decompose": True,
        "epic_title": "Epic: Big Work",
        "epic_body": "## Sub-issues",
        "children": [
            NewIssueSpec(title="Child 1", body="Do 1"),
            NewIssueSpec(title="Child 2", body="Do 2"),
        ],
        "reasoning": "Too complex for one pass",
    }
    defaults.update(overrides)
    return EpicDecompResult(**defaults)  # type: ignore[arg-type]


class TestCarryForwardPhrasing:
    """Every created child's body embeds the parent's stall context, with an
    explicit "don't repeat this" instruction -- not just the raw string.
    """

    @pytest.mark.asyncio
    async def test_child_body_contains_parent_stall_context_and_avoid_repeat_intent(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, _epic_manager, _state, _config = _make_decomposer(tmp_path)
        prs.add_issue(7, "Source issue", "Original body")
        source_task = TaskFactory.create(id=7)
        stall_context = "parent #7 stalled on flaky CI in module X"
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task,
            result=result,
            stall_context=stall_context,
        )

        assert epic_number is not None
        child_1 = prs.issue(epic_number + 1)
        child_2 = prs.issue(epic_number + 2)
        for child in (child_1, child_2):
            assert stall_context in child.body
            assert f"Parent #{source_task.id} stalled on:" in child.body
            assert "must not repeat that failure" in child.body

    @pytest.mark.asyncio
    async def test_no_stall_context_means_no_carry_forward_line(
        self, tmp_path: Path
    ) -> None:
        """No stall_context -> no "must not repeat" line at all (opt-in, not
        forced onto the plain intake-decomposition path).
        """
        decomposer, prs, _epic_manager, _state, _config = _make_decomposer(tmp_path)
        prs.add_issue(7, "Source issue", "Original body")
        source_task = TaskFactory.create(id=7)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result
        )

        assert epic_number is not None
        child_1 = prs.issue(epic_number + 1)
        assert "stalled on" not in child_1.body


class TestSalvageOrdering:
    """Salvage-marked children are created before the rest, regardless of
    their position in ``EpicDecompResult.children``.
    """

    @pytest.mark.asyncio
    async def test_salvage_labeled_child_created_first_regardless_of_position(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, _epic_manager, _state, _config = _make_decomposer(tmp_path)
        prs.add_issue(7, "Source issue", "Original body")
        source_task = TaskFactory.create(id=7)
        result = _two_child_result(
            children=[
                NewIssueSpec(title="Risky child A", body="New risky work"),
                NewIssueSpec(title="Risky child B", body="More risky work"),
                NewIssueSpec(
                    title="Land the working slice",
                    body="Ship the sound part",
                    labels=["salvage"],
                ),
            ]
        )

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result
        )

        assert epic_number is not None
        first_child = prs.issue(epic_number + 1)
        assert first_child.title == "Land the working slice"
        remaining_titles = {
            prs.issue(epic_number + 2).title,
            prs.issue(epic_number + 3).title,
        }
        assert remaining_titles == {"Risky child A", "Risky child B"}

    @pytest.mark.asyncio
    async def test_salvage_title_prefix_also_orders_first(self, tmp_path: Path) -> None:
        """The title-prefix form of the marker is accepted too, not just
        the labels form -- so a differently-shaped LLM reply still orders
        correctly.
        """
        decomposer, prs, _epic_manager, _state, _config = _make_decomposer(tmp_path)
        prs.add_issue(7, "Source issue", "Original body")
        source_task = TaskFactory.create(id=7)
        result = _two_child_result(
            children=[
                NewIssueSpec(title="Risky child A", body="New risky work"),
                NewIssueSpec(
                    title="[salvage] Land the working slice",
                    body="Ship the sound part",
                ),
            ]
        )

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result
        )

        assert epic_number is not None
        assert prs.issue(epic_number + 1).title == "[salvage] Land the working slice"
        assert prs.issue(epic_number + 2).title == "Risky child A"

    @pytest.mark.asyncio
    async def test_no_salvage_child_preserves_original_order(
        self, tmp_path: Path
    ) -> None:
        decomposer, prs, _epic_manager, _state, _config = _make_decomposer(tmp_path)
        prs.add_issue(7, "Source issue", "Original body")
        source_task = TaskFactory.create(id=7)
        result = _two_child_result()

        epic_number = await decomposer.create_epic_from_result(
            source_task=source_task, result=result
        )

        assert epic_number is not None
        assert prs.issue(epic_number + 1).title == "Child 1"
        assert prs.issue(epic_number + 2).title == "Child 2"


def _council(monkeypatch, *, results):
    """Wire a DecompositionCouncil whose seam call returns each of *results*
    in turn (as ``SimpleResult(stdout=..., returncode=0)``). Mirrors
    ``tests/test_decomposition_council.py``'s helper -- the LLM seam is
    always mocked here, never called for real.
    """
    from execution import SimpleResult

    calls: list[str] = []
    remaining = list(results)

    async def _fake_seam(**kwargs):
        calls.append(kwargs["prompt"])
        stdout = remaining.pop(0) if remaining else remaining[-1]
        return SimpleResult(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _fake_seam)
    council = DecompositionCouncil(runner=AsyncMock(), config=ConfigFactory.create())
    return council, calls


class TestCouncilSalvageIntegration:
    """The direction prompt is given the diff-so-far (packed into
    stall_context by the caller) and salvage instructions; a salvage-tagged
    child the council proposes survives parsing and lands first through
    IssueDecomposer.
    """

    @pytest.mark.asyncio
    async def test_direction_prompt_carries_diff_context_and_salvage_instructions(
        self, monkeypatch
    ) -> None:
        direction = json.dumps(
            {
                "epic_title": "Epic: split it",
                "epic_body": "## Sub-issues",
                "children": [
                    {"title": "Child A", "body": "Do A"},
                    {"title": "Child B", "body": "Do B"},
                ],
                "rationale": "Two lenses",
            }
        )
        validation = json.dumps(
            {"decision": "reject", "confidence": "high", "reasoning": "n/a"}
        )
        council, calls = _council(monkeypatch, results=[direction, validation])
        task = TaskFactory.create(id=7, title="Stalled task")

        await council.decide(
            task=task,
            stall_context=(
                "parent #7 stalled on flaky CI in module X\n\n"
                "diff-so-far: +142/-30 across 6 files"
            ),
            doc_context="",
            depth=0,
        )

        # The caller packs a diff summary into stall_context (no dedicated
        # param) -- it must reach the direction prompt verbatim.
        assert "diff-so-far: +142/-30 across 6 files" in calls[0]
        # Direction must be told it may scope a salvage child.
        assert "salvage" in calls[0].lower()

    @pytest.mark.asyncio
    async def test_council_output_with_salvage_child_lands_first_via_issue_decomposer(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        direction = json.dumps(
            {
                "epic_title": "Epic: split it",
                "epic_body": "## Sub-issues",
                "children": [
                    {
                        "title": "Risky child A",
                        "body": "New risky work",
                        "labels": [],
                    },
                    {
                        "title": "Land the working slice",
                        "body": "Ship the sound part",
                        "labels": ["salvage"],
                    },
                ],
                "rationale": "Salvage the sound part, retry the rest",
            }
        )
        validation = json.dumps(
            {"decision": "approve", "confidence": "high", "reasoning": "Sound split"}
        )
        council, _calls = _council(monkeypatch, results=[direction, validation])
        task = TaskFactory.create(id=7, title="Stalled task")

        result = await council.decide(
            task=task,
            stall_context="parent #7 stalled on flaky CI in module X",
            doc_context="",
            depth=0,
        )

        assert result.should_decompose is True
        assert any("salvage" in c.labels for c in result.children), (
            "the salvage label must survive JSON parsing onto NewIssueSpec.labels"
        )
        # The salvage child is second in the council's own output order --
        # proving IssueDecomposer (not the council) does the reordering.
        assert result.children[0].title == "Risky child A"

        decomposer, prs, _epic_manager, _state, _config = _make_decomposer(tmp_path)
        prs.add_issue(7, "Source issue", "Original body")

        epic_number = await decomposer.create_epic_from_result(
            source_task=task, result=result
        )

        assert epic_number is not None
        first_child = prs.issue(epic_number + 1)
        assert first_child.title == "Land the working slice"
