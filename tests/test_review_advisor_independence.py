"""Integration tests for judge-independence + fail-visible dispatch in the
PostVerifyAdvisor (#10371).

Exercises the ADDED lens on the existing verify path:
- a classed change routes its verdict to the independent model family;
- a fail-open (runner error) is ledgered + the disposition is a pass by default;
- a self-modification fail-open is fail-CLOSED (VETO) when the flag is on;
- degraded independence-unavailable is ledgered (never silent);
- unclassed changes take the untouched pre-#10371 path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import judge_independence as ji
from review_advisor import (
    SURFACE_ADVISOR_CONFIGS,
    PostVerifyAdvisor,
    PostVerifyInput,
)

_APPROVE = '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
_VETO = '{"verdict":"VETO","reasoning":"bad","disagreements":[]}'


class _StubRunner:
    def __init__(self, payload: str | Exception) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    async def run(
        self, *, model: str, subagent_type: str, prompt: str, role: str
    ) -> str:
        self.calls.append({"model": model, "role": role})
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _self_mod_diff() -> str:
    p = "src/convergence_gate.py"
    return f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n"


def _structural_diff() -> str:
    p = "docs/adr/0042-x.md"
    return f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n"


def _unclassed_diff() -> str:
    p = "src/comment_formatter.py"
    return f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n"


# ---------------------------------------------------------------------------
# Independence routing
# ---------------------------------------------------------------------------


def test_classed_change_routes_to_independent_model(tmp_path: Path):
    runner = _StubRunner(_APPROVE)
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        pr_number=42,
        judge_independence_enabled=True,
        independent_model="gpt-4o",
    )
    inp = PostVerifyInput(
        surface="pr_review",
        diff=_structural_diff(),
        executor_verdict_summary="approved",
    )
    asyncio.run(advisor.run(inp))
    # The dispatch went to the independent family, not the configured advisor.
    assert runner.calls[0]["model"] == "gpt-4o"
    records = ji.read_records(tmp_path / "l.jsonl")
    verdicts = [r for r in records if r["kind"] == ji.KIND_CLASSED_VERDICT]
    assert len(verdicts) == 1
    assert verdicts[0]["independent"] is True
    assert verdicts[0]["judge_family"] == "openai"


def test_unclassed_change_untouched(tmp_path: Path):
    runner = _StubRunner(_APPROVE)
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        judge_independence_enabled=True,
        independent_model="gpt-4o",
    )
    inp = PostVerifyInput(
        surface="pr_review",
        diff=_unclassed_diff(),
        executor_verdict_summary="approved",
    )
    asyncio.run(advisor.run(inp))
    # Ordinary path: dispatch stays on the configured advisor model, no records.
    assert runner.calls[0]["model"] == "opus"
    assert ji.read_records(tmp_path / "l.jsonl") == []


def test_flag_off_does_not_route_independently(tmp_path: Path):
    runner = _StubRunner(_APPROVE)
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        judge_independence_enabled=False,
        independent_model="gpt-4o",
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_structural_diff(), executor_verdict_summary="ok"
    )
    asyncio.run(advisor.run(inp))
    assert runner.calls[0]["model"] == "opus"


# ---------------------------------------------------------------------------
# Degraded independence-unavailable (never silent)
# ---------------------------------------------------------------------------


def test_degraded_same_family_ledgered_when_roster_empty(tmp_path: Path):
    runner = _StubRunner(_APPROVE)
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        judge_independence_enabled=True,
        independent_model="",  # no independent family configured
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_structural_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    assert result.verdict == "APPROVE"  # proceeds, but ledgered
    records = ji.read_records(tmp_path / "l.jsonl")
    unavail = [r for r in records if r["kind"] == ji.KIND_INDEPENDENCE_UNAVAILABLE]
    assert len(unavail) == 1
    assert unavail[0]["disposition"] == "degraded_same_family"


def test_self_mod_no_independent_escalates_hitl_when_fail_closed(tmp_path: Path):
    runner = _StubRunner(_APPROVE)
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        judge_independence_enabled=True,
        self_mod_fail_closed_enabled=True,
        independent_model="",
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_self_mod_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    # No independent verdict on the verdict-machinery → HITL escalation (VETO),
    # never dispatched to the same-family judge.
    assert result.verdict == "VETO"
    assert "HITL" in result.reasoning
    assert runner.calls == []
    unavail = [
        r
        for r in ji.read_records(tmp_path / "l.jsonl")
        if r["kind"] == ji.KIND_INDEPENDENCE_UNAVAILABLE
    ]
    assert unavail[0]["disposition"] == "degraded_self_mod_hitl"


# ---------------------------------------------------------------------------
# Fail-visible dispatch (runner error → fail-open)
# ---------------------------------------------------------------------------


def test_fail_open_is_ledgered_and_passes(tmp_path: Path):
    runner = _StubRunner(RuntimeError("dispatch boom"))
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        pr_number=99,
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_structural_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    assert result.verdict == "APPROVE"  # non-self-mod fails open
    fo = [
        r
        for r in ji.read_records(tmp_path / "l.jsonl")
        if r["kind"] == ji.KIND_FAIL_OPEN
    ]
    assert len(fo) == 1
    assert fo[0]["pr"] == 99
    assert fo[0]["disposition"] == "fail_open_ledgered"
    assert "structural" in fo[0]["failure_class"]


def test_self_mod_fail_open_is_fail_closed_when_flag_on(tmp_path: Path):
    runner = _StubRunner(RuntimeError("dispatch boom"))
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        self_mod_fail_closed_enabled=True,
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_self_mod_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    assert result.verdict == "VETO"  # fail-CLOSED for the self-mod class
    fo = [
        r
        for r in ji.read_records(tmp_path / "l.jsonl")
        if r["kind"] == ji.KIND_FAIL_OPEN
    ]
    assert fo[0]["disposition"] == "fail_closed_stop"
    assert fo[0]["self_modification"] is True


def test_self_mod_fail_open_passes_when_flag_off(tmp_path: Path):
    runner = _StubRunner(RuntimeError("boom"))
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        self_mod_fail_closed_enabled=False,
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_self_mod_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    # Feature-flagged: the STOP is opt-in. Still ledgered.
    assert result.verdict == "APPROVE"
    fo = [
        r
        for r in ji.read_records(tmp_path / "l.jsonl")
        if r["kind"] == ji.KIND_FAIL_OPEN
    ]
    assert fo[0]["disposition"] == "fail_open_ledgered"


def test_fail_open_raises_dashboard_alarm(tmp_path: Path):
    captured: list[Any] = []

    class _Bus:
        async def publish(self, event: Any) -> None:
            captured.append(event)

    runner = _StubRunner(RuntimeError("boom"))
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=tmp_path / "l.jsonl",
        event_bus=_Bus(),  # type: ignore[arg-type]
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_structural_diff(), executor_verdict_summary="ok"
    )
    asyncio.run(advisor.run(inp))
    assert len(captured) == 1
    assert captured[0].data["kind"] == "judge_fail_open"


def test_no_ledger_path_is_backwards_compatible(tmp_path: Path):
    """With no ledger_path/flags, behaviour is exactly pre-#10371 (fail-open pass)."""
    runner = _StubRunner(RuntimeError("boom"))
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_self_mod_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    assert result.verdict == "APPROVE"
