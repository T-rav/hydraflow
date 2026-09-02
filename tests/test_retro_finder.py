"""The LLM stage that turns signals into candidate findings (§3).

The finder proposes; the §4 validator disposes. Everything here is about
failing safely: a retro tick must never block the merge path, and it must never
swallow a billing signal.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retro_finder import RetroFinder, parse_findings  # noqa: E402
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


class TestParseTimeDropsAreCounted:
    """#11978: every way a response can fail to become findings is counted.

    The per-ITEM count was already right (#11903), which is exactly why the
    whole-response failure went unnoticed for so long: the counter existed and
    looked implemented, while the path that loses the most returned zero.
    """

    _VALID = {
        "kind": "gate",
        "signal_id": "tool_error-abc1234567",
        "title": "Guard the recurring failure",
        "guard_path": "tests/architecture/test_q.py",
        "observed": "7 occurrences",
    }

    def test_a_valid_response_reports_no_drops(self) -> None:
        findings, dropped = parse_findings(json.dumps([self._VALID]))

        assert (len(findings), dropped) == (1, 0)

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param("I could not find anything useful.", id="prose"),
            pytest.param('```json\n[{"kind"', id="truncated_fence"),
            pytest.param("", id="empty"),
            pytest.param('{"kind": "gate"}', id="object_not_array"),
        ],
    )
    def test_a_response_with_no_extractable_array_is_a_drop(self, raw: str) -> None:
        """The headline case: returning 0 here made a confabulating tick look clean."""
        findings, dropped = parse_findings(raw)

        assert findings == []
        assert dropped > 0, (
            "a response that yielded no findings at all reported zero drops, "
            "which a reader cannot tell from a model that correctly found nothing"
        )

    def test_items_failing_validation_are_counted_individually(self) -> None:
        findings, dropped = parse_findings(json.dumps([{"kind": "gate"}, {"nope": 1}]))

        assert (findings, dropped) == ([], 2)

    def test_a_mixed_response_keeps_the_valid_and_counts_the_rest(self) -> None:
        findings, dropped = parse_findings(json.dumps([self._VALID, {"nope": 1}]))

        assert (len(findings), dropped) == (1, 1)


class TestTheDropCountIsPerTick:
    """A counter that survives a tick reports drops that tick did not have."""

    async def test_an_empty_response_does_not_inherit_the_previous_count(
        self, tmp_path
    ) -> None:
        """#11978: the empty path returned without touching `unparseable`.

        A tick that dropped three items followed by one that got no response at
        all published three drops for the second tick. Found while wiring the
        scenario: the early `if not raw: return []` skips `parse_findings`
        entirely, so the attribute simply kept its old value.
        """
        finder = RetroFinder(
            ConfigFactory.create(repo_root=tmp_path),
            AsyncMock(),
            MagicMock(gh_token=""),
        )
        finder.unparseable = 3

        with patch.object(RetroFinder, "_call_model", new=AsyncMock(return_value="")):
            findings = await finder.find([SIGNAL])

        assert findings == []
        assert finder.unparseable == 0, (
            "an empty response inherited the previous tick's drop count"
        )
