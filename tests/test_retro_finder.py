"""The LLM stage that turns signals into candidate findings (§3).

The finder proposes; the §4 validator disposes. Everything here is about
failing safely: a retro tick must never block the merge path, and it must never
swallow a billing signal.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retro_finder import RetroFinder  # noqa: E402
from retro_signals import EvidenceRef, RetroSignal  # noqa: E402
from subprocess_util import CreditExhaustedError  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402

SIGNAL = RetroSignal(
    id="tool_error-abc1234567",
    family="tool_error",
    signature="Bash: make quality failed",
    count=7,
    issues=[1, 2],
    evidence=[EvidenceRef(locator="traces/1/x", excerpt="make: *** [quality] Error 1")],
)

VALID_JSON = json.dumps(
    [
        {
            "kind": "gate",
            "signal_id": SIGNAL.id,
            "title": "Guard repeated quality failures",
            "guard_path": "tests/architecture/test_q.py",
            "observed": "7 occurrences",
        }
    ]
)


def _config(**over):
    config = ConfigFactory.create()
    config.retro_finder_enabled = True
    for key, value in over.items():
        setattr(config, key, value)
    return config


def _result(stdout: str, returncode: int = 0):
    class _R:
        pass

    r = _R()
    r.stdout = stdout
    r.stderr = ""
    r.returncode = returncode
    return r


def _finder(config=None):
    return RetroFinder(config or _config())


class TestGating:
    @pytest.mark.asyncio
    async def test_disabled_finder_returns_nothing_and_never_spawns(self):
        with patch("runner_utils.run_lightweight_agent", new=AsyncMock()) as spawn:
            findings = await _finder(_config(retro_finder_enabled=False)).find([SIGNAL])

        assert findings == []
        spawn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_signals_means_no_spawn(self):
        with patch("runner_utils.run_lightweight_agent", new=AsyncMock()) as spawn:
            findings = await _finder().find([])

        assert findings == []
        spawn.assert_not_awaited()


class TestParsing:
    @pytest.mark.asyncio
    async def test_valid_json_becomes_typed_findings(self):
        with patch(
            "runner_utils.run_lightweight_agent",
            new=AsyncMock(return_value=_result(VALID_JSON)),
        ):
            findings = await _finder().find([SIGNAL])

        assert len(findings) == 1
        assert findings[0].kind == "gate"
        assert findings[0].guard_path == "tests/architecture/test_q.py"

    @pytest.mark.asyncio
    async def test_json_wrapped_in_a_markdown_fence_is_still_parsed(self):
        fenced = f"Here you go:\n```json\n{VALID_JSON}\n```\n"
        with patch(
            "runner_utils.run_lightweight_agent",
            new=AsyncMock(return_value=_result(fenced)),
        ):
            findings = await _finder().find([SIGNAL])

        assert len(findings) == 1

    @pytest.mark.asyncio
    async def test_unknown_kind_is_skipped_without_losing_the_rest(self):
        payload = json.dumps(
            [
                {"kind": "telepathy", "signal_id": SIGNAL.id, "title": "?"},
                json.loads(VALID_JSON)[0],
            ]
        )
        with patch(
            "runner_utils.run_lightweight_agent",
            new=AsyncMock(return_value=_result(payload)),
        ):
            findings = await _finder().find([SIGNAL])

        assert [f.kind for f in findings] == ["gate"]

    @pytest.mark.asyncio
    async def test_a_finding_missing_its_anchor_is_skipped(self):
        payload = json.dumps(
            [{"kind": "gate", "signal_id": SIGNAL.id, "title": "x", "observed": "7"}]
        )
        with patch(
            "runner_utils.run_lightweight_agent",
            new=AsyncMock(return_value=_result(payload)),
        ):
            assert await _finder().find([SIGNAL]) == []


class TestFailureSemantics:
    @pytest.mark.parametrize(
        "spawn",
        [
            AsyncMock(return_value=_result("", returncode=1)),
            AsyncMock(side_effect=TimeoutError),
            AsyncMock(return_value=_result("not json at all")),
        ],
        ids=["nonzero_rc", "timeout", "unparseable"],
    )
    @pytest.mark.asyncio
    async def test_every_degraded_backend_yields_nothing(self, spawn):
        """A retro tick is best-effort — it must never block the merge path."""
        with patch("runner_utils.run_lightweight_agent", new=spawn):
            assert await _finder().find([SIGNAL]) == []

    @pytest.mark.asyncio
    async def test_credit_exhaustion_propagates_rather_than_being_swallowed(self):
        """Burying this leaves the loop spawning against a dead account."""
        with (
            patch(
                "runner_utils.run_lightweight_agent",
                new=AsyncMock(side_effect=CreditExhaustedError("out of credit")),
            ),
            pytest.raises(CreditExhaustedError),
        ):
            await _finder().find([SIGNAL])


class TestPromptGrounding:
    @pytest.mark.asyncio
    async def test_prompt_carries_signal_ids_and_evidence(self):
        spawn = AsyncMock(return_value=_result(VALID_JSON))
        with patch("runner_utils.run_lightweight_agent", new=spawn):
            await _finder().find([SIGNAL])

        prompt = spawn.await_args.kwargs["prompt"]
        assert SIGNAL.id in prompt
        assert "make: *** [quality] Error 1" in prompt

    @pytest.mark.asyncio
    async def test_prompt_respects_the_excerpt_budget(self):
        big = RetroSignal(
            id="tool_error-big0000000",
            family="tool_error",
            signature="x",
            count=1,
            issues=[1],
            evidence=[EvidenceRef(locator="l", excerpt="E" * 100_000)],
        )
        spawn = AsyncMock(return_value=_result("[]"))
        with patch("runner_utils.run_lightweight_agent", new=spawn):
            await _finder(_config(retro_evidence_max_chars=5_000)).find([big])

        assert len(spawn.await_args.kwargs["prompt"]) < 20_000


class TestDataClassElevation:
    @pytest.mark.asyncio
    async def test_issue_labels_reach_the_spawn(self):
        """CH-6 needs them for upward-only data-class elevation."""
        spawn = AsyncMock(return_value=_result("[]"))
        with patch("runner_utils.run_lightweight_agent", new=spawn):
            await _finder().find([SIGNAL], issue_labels=["data-class:secret"])

        assert spawn.await_args.kwargs["issue_labels"] == ["data-class:secret"]
