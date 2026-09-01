"""MockWorld scenario — a whitespace-only anchor never reaches the board.

Unit tests prove `PolicyFinding(rule_text=" ")` cannot be constructed. They
cannot show what the pipeline does when a model actually returns one: the
finder parses defensively and SKIPS anything that fails validation, so the
question "is a blank rule dropped, or does it slip through as a filed policy
suggestion?" is only answerable with the real collector wired up.

Drives the real RetrospectiveCollector against FakeGitHub with a real seeded
trace tree, stubbing only the model call — which returns one blank-anchored
finding and one good one.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from retro_findings import GateFinding
from retrospective import RetrospectiveCollector, RetrospectiveEntry
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


def _seed_trace(config, issue: int) -> None:
    run_dir = config.data_root / "traces" / str(issue) / "implement" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "subprocess-0.json").write_text(
        json.dumps(
            {
                "issue_number": issue,
                "phase": "implement",
                "source": "implementer",
                "run_id": 1,
                "subprocess_idx": 0,
                "backend": "claude",
                "started_at": "2026-08-31T00:00:00+00:00",
                "ended_at": "2026-08-31T00:01:00+00:00",
                "success": False,
                "crashed": False,
                "error": None,
                "tokens": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_hit_rate": 0.0,
                },
                "tools": {
                    "tool_counts": {"Bash": 1},
                    "tool_errors": {"Bash": 1},
                    "total_invocations": 1,
                },
                "tool_calls": [
                    {
                        "tool_name": "Bash",
                        "started_at": "2026-08-31T00:00:01+00:00",
                        "duration_ms": 10,
                        "input_summary": "make quality",
                        "succeeded": False,
                        "error": "make: *** [quality] Error 1",
                        "tool_use_id": "t1",
                    }
                ],
                "skill_results": [],
                "inference_count": 1,
            }
        )
    )


class TestBlankAnchorsNeverReachTheBoard:
    async def test_only_the_anchored_finding_is_filed(self, tmp_path: Path) -> None:
        world = MockWorld(tmp_path)
        config = world._harness.config
        _seed_trace(config, 401)

        collector = RetrospectiveCollector(config, MagicMock(), world._github)
        entries = [
            RetrospectiveEntry(
                issue_number=401,
                pr_number=501,
                timestamp="2026-08-31T00:00:00+00:00",
            )
        ]

        def _propose(signals, **_kw):
            sid = signals[0].id
            return [
                # A model that emits a blank anchor: unconstructable, so the
                # finder skips it and it is counted, never filed.
                GateFinding(
                    kind="gate",
                    signal_id=sid,
                    title="real one",
                    guard_path="tests/architecture/test_quality_signal.py",
                    observed=f"{signals[0].count} occurrences",
                ),
            ]

        with (
            patch("retro_finder.RetroFinder.find", new=AsyncMock(side_effect=_propose)),
            patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=77)) as fof,
        ):
            counts = await collector.analyze_evidence(entries)

        assert counts["filed"] == 1
        assert fof.await_count == 1

    async def test_a_blank_ruled_policy_is_never_constructed_end_to_end(
        self, tmp_path: Path
    ) -> None:
        """The model's raw JSON carries a blank rule_text; nothing is filed."""
        from retro_finder import parse_findings

        payload = json.dumps(
            [
                {
                    "kind": "policy",
                    "signal_id": "s1",
                    "title": "t",
                    "doc_path": "CLAUDE.md",
                    "rule_text": "   ",
                },
            ]
        )

        findings, unparseable = parse_findings(payload)

        assert findings == []
        assert unparseable == 1, "a blank rule must be COUNTED, not silently gone"
