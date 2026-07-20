"""Regression tests for issue #9998 — skill-name telemetry source tagging.

Before the fix, every post-implementation skill spawn (diff-sanity,
scope-check, plan-compliance, test-adequacy) recorded PromptTelemetry under
the coarse phase source ``"implementer"``, and the Discover/Shape evaluator
spawns under ``"discover:evaluator"`` / ``"shape:evaluator"``. As a result
``PromptTelemetry.get_source_totals()`` never contained skill-name keys and
``pick_refine_order`` (src/prompt_efficiency.py) was a graceful no-op in
production — its rank lookup keys on a corpus case's ``expected_catcher``
(bare skill names) and never matched a telemetry row.

The fix threads a telemetry-only ``telemetry_source`` override through
``BaseRunner._execute`` so PromptTelemetry aggregates per skill, while
``event_data["source"]`` keeps its phase tag — that tag is load-bearing for
MockWorld/scenario transcript scripting (keyed on source prefixes) and the
dashboard event stream, so it must NOT change.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent import AgentRunner
from base_runner import BaseRunner
from discover_runner import DiscoverRunner
from events import EventBus
from model_pricing import ModelPricingTable
from models import Task
from prompt_efficiency import compute_skill_efficiency, pick_refine_order
from prompt_telemetry import PromptTelemetry
from shape_runner import ShapeRunner
from skill_registry import BUILTIN_SKILLS
from tests.helpers import ConfigFactory

# The four blocking skills named by #9998's acceptance criterion.
_BLOCKING_SKILL_NAMES = [s.name for s in BUILTIN_SKILLS if s.blocking]

_DIFF_SANITY_OK = "DIFF_SANITY_RESULT: OK\nSUMMARY: No issues found"
_DISCOVER_OK = "DISCOVER_COMPLETENESS_RESULT: OK\nSUMMARY: complete"
_SHAPE_OK = "SHAPE_COHERENCE_RESULT: OK\nSUMMARY: coherent"


def _make_task(number: int = 42) -> Task:
    return Task(
        id=number,
        title="Fix the frobnicator",
        body="The frobnicator is broken.",
        tags=["ready"],
        comments=[],
        source_url=f"https://github.com/test-org/test-repo/issues/{number}",
    )


def _make_base_runner(tmp_path: Path) -> BaseRunner:
    """Bare BaseRunner via __new__ — same scaffold as test_base_runner_execute_trace."""
    config = MagicMock()
    config.data_root = tmp_path
    config.agent_timeout = 60
    # CH-6 prompt gate reads the data class in _execute; the MagicMock
    # default would fail closed as an unknown class, so pin the no-op class.
    config.repo_data_class = "internal"
    event_bus = MagicMock()
    event_bus.current_session_id = None
    br = BaseRunner.__new__(BaseRunner)
    br._config = config
    br._bus = event_bus
    br._active_procs = set()
    br._runner = MagicMock()
    br._prompt_telemetry = MagicMock()
    br._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
    br._hindsight = None
    br._tracing_ctx = None
    br._credentials = MagicMock()
    br._credentials.gh_token = ""
    br._wiki_store = None
    br._log = MagicMock()
    return br


class TestExecuteTelemetrySourceOverride:
    """BaseRunner._execute honors a telemetry-only source override."""

    @pytest.mark.asyncio
    async def test_override_reaches_prompt_telemetry_record(
        self, tmp_path: Path
    ) -> None:
        runner = _make_base_runner(tmp_path)

        async def fake_stream(**kwargs):
            return "transcript"

        with patch("base_runner.stream_claude_process", side_effect=fake_stream):
            await runner._execute(
                cmd=["claude", "-p"],
                prompt="check this diff",
                cwd=tmp_path,
                event_data={"issue": 42, "source": "implementer"},
                telemetry_source="diff-sanity",
            )

        record_kwargs = runner._prompt_telemetry.record.call_args.kwargs
        assert record_kwargs["source"] == "diff-sanity"

    @pytest.mark.asyncio
    async def test_without_override_source_comes_from_event_data(
        self, tmp_path: Path
    ) -> None:
        """Pin the pre-existing default: event_data['source'] attribution."""
        runner = _make_base_runner(tmp_path)

        async def fake_stream(**kwargs):
            return "transcript"

        with patch("base_runner.stream_claude_process", side_effect=fake_stream):
            await runner._execute(
                cmd=["claude", "-p"],
                prompt="implement the thing",
                cwd=tmp_path,
                event_data={"issue": 42, "source": "implementer"},
            )

        record_kwargs = runner._prompt_telemetry.record.call_args.kwargs
        assert record_kwargs["source"] == "implementer"


class TestSkillSpawnsTagTelemetryWithSkillName:
    """Each skill-invocation path passes its skill name as telemetry_source
    while leaving event_data['source'] (scenario-scripting key) untouched."""

    @pytest.mark.asyncio
    async def test_run_skill_passes_skill_name(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        config.max_diff_sanity_attempts = 1
        runner = AgentRunner(config, event_bus)
        diff_sanity = next(s for s in BUILTIN_SKILLS if s.name == "diff-sanity")
        with (
            patch.object(
                runner, "_count_commits", new_callable=AsyncMock, return_value=1
            ),
            patch.object(
                runner,
                "_get_branch_diff",
                new_callable=AsyncMock,
                return_value="+import os\n",
            ),
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                return_value=_DIFF_SANITY_OK,
            ) as execute_mock,
        ):
            result = await runner._run_skill(
                diff_sanity, _make_task(), tmp_path, "branch", worker_id=0
            )

        assert result.passed is True
        call = execute_mock.await_args
        assert call.kwargs["telemetry_source"] == "diff-sanity"
        # The event source stays the phase tag — scenario stubs key on it.
        assert call.args[3]["source"] == "implementer"

    @pytest.mark.asyncio
    async def test_discover_evaluator_passes_skill_name(self, config) -> None:
        config.dry_run = False
        runner = DiscoverRunner(config=config, event_bus=MagicMock(spec=EventBus))
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                return_value=_DISCOVER_OK,
            ) as execute_mock,
            patch.object(runner, "_build_command", return_value=["claude"]),
        ):
            await runner._evaluate_brief(_make_task(7), "a non-empty brief")

        call = execute_mock.await_args
        assert call.kwargs["telemetry_source"] == "discover-completeness"
        assert call.args[3]["source"] == "discover:evaluator"

    @pytest.mark.asyncio
    async def test_shape_evaluator_passes_skill_name(self, config) -> None:
        config.dry_run = False
        runner = ShapeRunner(config=config, event_bus=MagicMock(spec=EventBus))
        with (
            patch.object(
                runner,
                "_execute",
                new_callable=AsyncMock,
                return_value=_SHAPE_OK,
            ) as execute_mock,
            patch.object(runner, "_build_command", return_value=["claude"]),
        ):
            await runner._evaluate_proposal(
                _make_task(9), "a discover brief", "a proposal"
            )

        call = execute_mock.await_args
        assert call.kwargs["telemetry_source"] == "shape-coherence"
        assert call.args[3]["source"] == "shape:evaluator"


class TestSkillSourcesDriveRefineOrder:
    """Acceptance shape from #9998: once sources are skill names,
    totals_by_source() contains the blocking skills as keys and
    pick_refine_order produces a non-identity ordering when costs differ."""

    def test_blocking_skill_sources_produce_nonidentity_refine_order(
        self, tmp_path: Path
    ) -> None:
        pricing_path = tmp_path / "pricing.json"
        pricing_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "models": {
                        "claude-sonnet-4-20250514": {
                            "input_cost_per_million": 3.0,
                            "output_cost_per_million": 15.0,
                            "aliases": ["sonnet"],
                        }
                    },
                }
            )
        )
        telemetry_config = ConfigFactory.create(repo_root=tmp_path)
        telemetry = PromptTelemetry(
            telemetry_config, pricing=ModelPricingTable(pricing_path)
        )
        assert len(_BLOCKING_SKILL_NAMES) == 4

        # Cheapest-first seeding: cost rises with position, so the
        # worst-first efficiency ranking must invert the seeded order.
        for i, skill_name in enumerate(_BLOCKING_SKILL_NAMES):
            telemetry.record(
                source=skill_name,
                tool="claude",
                model="sonnet",
                issue_number=100 + i,
                pr_number=None,
                session_id="sess-9998",
                prompt_chars=1000,
                transcript_chars=500,
                duration_seconds=1.0,
                success=True,
                stats={
                    "input_tokens": 1000 * (i + 1),
                    "output_tokens": 500 * (i + 1),
                },
            )

        totals_by_source = telemetry.get_source_totals()
        for skill_name in _BLOCKING_SKILL_NAMES:
            assert skill_name in totals_by_source, (
                f"{skill_name!r} missing from get_source_totals() keys: "
                f"{sorted(totals_by_source)}"
            )

        rows = compute_skill_efficiency(totals_by_source, baseline=None)
        cases = [
            {"case_id": f"case-{name}", "expected_catcher": name}
            for name in _BLOCKING_SKILL_NAMES
        ]
        ordered = pick_refine_order(cases, rows)
        assert ordered != cases, (
            "pick_refine_order returned the identity ordering even though "
            "per-skill costs differ"
        )
        # Most cost-inefficient skill (the last-seeded, most expensive one)
        # gets first crack at the refine cap.
        assert ordered[0]["expected_catcher"] == _BLOCKING_SKILL_NAMES[-1]
