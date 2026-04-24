"""MockWorld scenario for the product-phase trust pipeline (spec §4.10 — Task 15).

Covers the upstream half of the lights-off pipeline: a vague issue flows
through :class:`DiscoverPhase` (which exercises the retry path — evaluator
returns RETRY on the first brief, OK on the second) and then through
:class:`ShapePhase` (which finalizes on the first turn), and must land on
the next pipeline label (``hydraflow-plan``) with no ``hitl-escalation``
filed.

Unlike the existing scenarios that drive :class:`PipelineHarness`'s
triage/plan/implement/review methods, this scenario wires the real
``DiscoverPhase`` and ``ShapePhase`` coordinators on top of the harness's
shared ``IssueStore`` / ``StateTracker`` / ``EventBus``, using
``FakeGitHub`` as the :class:`PRManager` and real runner objects whose
``_execute`` method is scripted per ``source`` tag. This keeps the test
deterministic without widening :class:`FakeLLM` to know about the
discover/shape runners (see Task-15 plan notes, simplified path).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from discover_phase import DiscoverPhase
from discover_runner import DiscoverRunner
from models import Task
from shape_phase import ShapePhase
from shape_runner import ShapeRunner
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


_AMBIGUOUS_BODY = (
    "Maybe we should add a dark mode? Not sure if per-device or per-account. "
    "It depends on what users expect."
)

_BAD_BRIEF_JSON = (
    "DISCOVER_START\n```json\n"
    '{"issue_number": 501, "research_brief": "Maybe a dark mode. The app.",'
    ' "competitors": [], "user_needs": [], "opportunities": []}\n'
    "```\nDISCOVER_END"
)

_GOOD_BRIEF_JSON = (
    "DISCOVER_START\n```json\n"
    '{"issue_number": 501, "research_brief": '
    '"## Intent\\nAdd a dark mode toggle to the settings page.\\n\\n'
    "## Affected area\\nsrc/ui/settings, src/ui/theme.ts.\\n\\n"
    "## Acceptance criteria\\n- Toggle visible at /settings/appearance.\\n"
    "- Preference persists across reload (localStorage key theme-pref).\\n"
    "- prefers-color-scheme respected when set to auto.\\n\\n"
    "## Open questions\\n- Per-device or per-account persistence?\\n"
    "- Feature-flag gated for staged rollout?\\n\\n"
    '## Known unknowns\\nAccessibility for inline charts in dark mode.",'
    ' "competitors": ["Linear (per-account)", "VS Code (per-device)"],'
    ' "user_needs": ["Eye strain in dim environments"],'
    ' "opportunities": ["Auto-follow OS with manual override"]}\n'
    "```\nDISCOVER_END"
)

_SHAPE_FINAL_PROPOSAL = (
    "SHAPE_FINALIZE\n"
    "## Final Product Direction\n\n"
    "**Problem**: Users want a dark mode without relearning navigation.\n"
    "**Approach**: Per-account theme preference synced across devices.\n"
    "**Scope**: Settings toggle + auto-follow OS. Out: custom palettes.\n"
    "**Success criteria**: Toggle lands; preference persists.\n"
    "**Key risks**: Inline chart contrast.\n"
    "SHAPE_FINALIZE_END"
)


def _retry_eval_transcript(keyword: str = "missing-section:acceptance-criteria") -> str:
    """Build a scripted discover-completeness RETRY evaluator transcript."""
    return (
        f"DISCOVER_COMPLETENESS_RESULT: RETRY\n"
        f"SUMMARY: {keyword} — brief lacks required section\n"
        f"FINDINGS:\n- {keyword} — evidence pulled from brief\n"
    )


_OK_DISCOVER_EVAL = (
    "DISCOVER_COMPLETENESS_RESULT: OK\nSUMMARY: All five rubric criteria pass\n"
)

_OK_SHAPE_EVAL = "SHAPE_COHERENCE_RESULT: OK\nSUMMARY: All rubric criteria pass\n"


def _build_execute_stub(
    script: dict[str, list[str]],
    call_log: list[str],
) -> Any:
    """Build an ``_execute`` side_effect that pops transcripts keyed by source tag.

    The runner's ``_execute`` signature is
    ``(cmd, prompt, cwd, event_data, *, on_output=None)``. ``event_data``
    carries a ``"source"`` key like ``"discover:attempt-1"`` /
    ``"discover:evaluator"`` / ``"shape:attempt-1"`` /
    ``"shape:evaluator"`` that we use to pick the right scripted transcript.
    """
    queues = {k: list(v) for k, v in script.items()}

    async def _fake_execute(
        _cmd: list[str],
        _prompt: str,
        _cwd: Any,
        event_data: dict[str, Any],
        *,
        on_output: Any = None,
    ) -> str:
        _ = on_output
        source = str(event_data.get("source", ""))
        call_log.append(source)
        # Pick the queue whose key is a prefix of the source tag. Sources
        # like "discover:attempt-1" and "discover:attempt-2" share the
        # "discover:attempt" prefix; "discover:evaluator" has its own.
        for key in sorted(queues, key=len, reverse=True):
            if source.startswith(key):
                q = queues[key]
                if not q:
                    raise AssertionError(
                        f"script exhausted for source={source!r}: no more transcripts"
                    )
                return q.pop(0)
        raise AssertionError(f"no scripted transcript for source={source!r}")

    return _fake_execute


def _wire_discover_phase(
    world: MockWorld,
    *,
    max_attempts: int,
    call_log: list[str],
    discover_script: dict[str, list[str]],
) -> DiscoverPhase:
    """Construct a real DiscoverPhase wired against the MockWorld harness."""
    harness = world.harness
    harness.config.max_discover_attempts = max_attempts
    harness.config.dry_run = False
    # FakeGitHub is the canonical PRManager for scenario tests — swap it in.
    harness.prs = world.github
    # Fetcher returns no comments so enrich_with_comments is a no-op.
    harness.fetcher.fetch_issue_comments = AsyncMock(return_value=[])

    runner = DiscoverRunner(config=harness.config, event_bus=harness.bus)
    runner._execute = AsyncMock(  # type: ignore[assignment]
        side_effect=_build_execute_stub(discover_script, call_log)
    )
    runner._build_command = lambda _w=None: ["claude"]  # type: ignore[assignment]
    runner._inject_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    runner._save_transcript = lambda *a, **k: None  # type: ignore[assignment]

    return DiscoverPhase(
        config=harness.config,
        state=harness.state,
        store=harness.store,
        prs=world.github,  # type: ignore[arg-type]
        event_bus=harness.bus,
        stop_event=harness.stop_event,
        discover_runner=runner,
    )


def _wire_shape_phase(
    world: MockWorld,
    *,
    max_attempts: int,
    call_log: list[str],
    shape_script: dict[str, list[str]],
) -> ShapePhase:
    """Construct a real ShapePhase wired against the MockWorld harness."""
    harness = world.harness
    harness.config.max_shape_attempts = max_attempts
    harness.config.max_shape_turns = 1  # finalize immediately on first turn
    harness.config.dry_run = False

    runner = ShapeRunner(config=harness.config, event_bus=harness.bus)
    runner._execute = AsyncMock(  # type: ignore[assignment]
        side_effect=_build_execute_stub(shape_script, call_log)
    )
    runner._build_command = lambda _w=None: ["claude"]  # type: ignore[assignment]
    runner._inject_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    runner._save_transcript = lambda *a, **k: None  # type: ignore[assignment]

    return ShapePhase(
        config=harness.config,
        state=harness.state,
        store=harness.store,
        prs=world.github,  # type: ignore[arg-type]
        event_bus=harness.bus,
        stop_event=harness.stop_event,
        shape_runner=runner,
    )


class TestProductPhaseTrustScenario:
    """§4.10 — end-to-end Discover (RETRY→OK) → Shape → transition-to-plan."""

    async def test_discover_retry_then_shape_then_plan(self, tmp_path) -> None:
        """Happy path: bad brief → RETRY → good brief → OK → shape finalizes → plan."""
        world = MockWorld(tmp_path)

        # Seed the issue into FakeGitHub AND the harness's discover queue.
        world.add_issue(
            501,
            "Maybe a dark mode?",
            _AMBIGUOUS_BODY,
            labels=["hydraflow-discover"],
        )
        task = Task(
            id=501,
            title="Maybe a dark mode?",
            body=_AMBIGUOUS_BODY,
            tags=["hydraflow-discover"],
        )
        world.harness.seed_issue(task, stage="discover")

        call_log: list[str] = []

        # Discover scripts: two attempts on the runner, two evaluator calls.
        discover_script = {
            "discover:attempt": [_BAD_BRIEF_JSON, _GOOD_BRIEF_JSON],
            "discover:evaluator": [
                _retry_eval_transcript(),
                _OK_DISCOVER_EVAL,
            ],
        }
        shape_script = {
            "shape:attempt": [_SHAPE_FINAL_PROPOSAL],
            "shape:evaluator": [_OK_SHAPE_EVAL],
        }

        discover_phase = _wire_discover_phase(
            world,
            max_attempts=3,
            call_log=call_log,
            discover_script=discover_script,
        )
        shape_phase = _wire_shape_phase(
            world,
            max_attempts=3,
            call_log=call_log,
            shape_script=shape_script,
        )

        # --- Run Discover: produces brief, transitions issue to shape ---
        did_discover = await discover_phase.discover_issues()
        assert did_discover, "DiscoverPhase should process the seeded issue"

        # Discover retry path exercised: two _run_discovery_once calls,
        # plus two evaluator dispatches (first RETRY, second OK).
        discover_attempts = [c for c in call_log if c.startswith("discover:attempt")]
        discover_evals = [c for c in call_log if c == "discover:evaluator"]
        assert len(discover_attempts) == 2, (
            f"expected 2 discover attempts (RETRY→OK), got {discover_attempts}"
        )
        assert len(discover_evals) == 2, (
            f"expected 2 evaluator dispatches, got {discover_evals}"
        )

        # FakeGitHub's transition advanced the issue into shape.
        labels_after_discover = world.github.issue(501).labels
        assert "hydraflow-shape" in labels_after_discover, labels_after_discover

        # --- Run Shape: finalizes on first turn, transitions to plan ---
        did_shape = await shape_phase.shape_issues()
        assert did_shape, "ShapePhase should finalize the seeded issue"

        # Shape hit exactly one turn (finalized immediately) + one evaluator pass.
        shape_attempts = [c for c in call_log if c.startswith("shape:attempt")]
        shape_evals = [c for c in call_log if c == "shape:evaluator"]
        assert len(shape_attempts) == 1, shape_attempts
        assert len(shape_evals) == 1, shape_evals

        # The final assertion: the issue lands on the plan label.
        labels_after_shape = world.github.issue(501).labels
        assert "hydraflow-plan" in labels_after_shape, labels_after_shape

        # No escalation issues filed (no hitl-escalation label anywhere).
        escalations = [
            i for i in world.github._issues.values() if "hitl-escalation" in i.labels
        ]
        assert not escalations, (
            f"unexpected hitl-escalation issues filed: "
            f"{[(i.number, i.title, i.labels) for i in escalations]}"
        )

    async def test_discover_exhaustion_files_escalation(self, tmp_path) -> None:
        """Sad path: max_discover_attempts RETRYs → hitl-escalation filed."""
        world = MockWorld(tmp_path)

        world.add_issue(
            502,
            "Ambiguous thing",
            _AMBIGUOUS_BODY,
            labels=["hydraflow-discover"],
        )
        task = Task(
            id=502,
            title="Ambiguous thing",
            body=_AMBIGUOUS_BODY,
            tags=["hydraflow-discover"],
        )
        world.harness.seed_issue(task, stage="discover")

        call_log: list[str] = []

        # Two bad briefs, two RETRY evaluations — exhausts the budget.
        discover_script = {
            "discover:attempt": [_BAD_BRIEF_JSON, _BAD_BRIEF_JSON],
            "discover:evaluator": [
                _retry_eval_transcript("missing-section:acceptance-criteria"),
                _retry_eval_transcript("paraphrase-only"),
            ],
        }

        discover_phase = _wire_discover_phase(
            world,
            max_attempts=2,
            call_log=call_log,
            discover_script=discover_script,
        )

        await discover_phase.discover_issues()

        # Escalation issue filed with hitl-escalation + discover-stuck labels.
        escalations = [
            i
            for i in world.github._issues.values()
            if "hitl-escalation" in i.labels and "discover-stuck" in i.labels
        ]
        assert len(escalations) == 1, (
            f"expected one hitl-escalation/discover-stuck issue, got "
            f"{[(i.number, i.title, i.labels) for i in escalations]}"
        )
        assert "#502" in escalations[0].title

        # Asyncio bookkeeping: let the bus drain any queued events cleanly.
        await asyncio.sleep(0)
