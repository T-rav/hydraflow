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


def test_classification_paths_classes_a_headerless_diff(tmp_path: Path):
    """A header-less "diff" classifies via ``classification_paths``.

    The ADR-review surface passes the ADR body as ``diff`` (no ``+++ b/`` /
    ``diff --git`` headers, so ``classify_diff`` finds nothing) plus
    ``classification_paths`` declaring the ADR corpus. The union classifies
    STRUCTURAL and routes to the independent family — the fix for the
    ADR-review classification bypass, tested at the advisor unit level.
    """
    runner = _StubRunner(_APPROVE)
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["adr_review"],
        ledger_path=tmp_path / "l.jsonl",
        judge_independence_enabled=True,
        independent_model="gpt-4o",
    )
    inp = PostVerifyInput(
        surface="adr_review",
        diff="# ADR-1234\n## Decision\nNo unified-diff headers appear here.\n",
        executor_verdict_summary="ok",
        classification_paths=["docs/adr/"],
    )
    asyncio.run(advisor.run(inp))
    assert runner.calls[0]["model"] == "gpt-4o"
    classed = [
        r
        for r in ji.read_records(tmp_path / "l.jsonl")
        if r["kind"] == ji.KIND_CLASSED_VERDICT
    ]
    assert len(classed) == 1
    assert "structural" in classed[0]["failure_class"]


def test_no_classification_paths_leaves_headerless_diff_unclassed(tmp_path: Path):
    """Control for the test above: WITHOUT ``classification_paths`` the same
    header-less body is still unclassed (same-family dispatch, no row) — proving
    the field is the load-bearing difference, not the body content."""
    runner = _StubRunner(_APPROVE)
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["adr_review"],
        ledger_path=tmp_path / "l.jsonl",
        judge_independence_enabled=True,
        independent_model="gpt-4o",
    )
    inp = PostVerifyInput(
        surface="adr_review",
        diff="# ADR-1234\n## Decision\nNo unified-diff headers appear here.\n",
        executor_verdict_summary="ok",
    )
    asyncio.run(advisor.run(inp))
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


def test_flag_off_classed_success_is_inert_no_ledger_no_bus(tmp_path: Path):
    """Flag-off + classed change + SUCCESS path is fully inert.

    The ledger/alarm are "always live" only for fail-open / degraded events —
    on a flag-off SUCCESS path there is nothing to record: no independence
    routing, no classed-verdict row, no fail-open row, and no bus publish. A spy
    on BOTH the ledger file and the event bus proves zero writes / zero
    publishes, so a regression that made ledgering unconditional (or dropped the
    flag guard on independence routing) fails here — not just the dispatch-model
    check above.
    """
    published: list[Any] = []

    class _SpyBus:
        async def publish(self, event: Any) -> None:
            published.append(event)

    runner = _StubRunner(_APPROVE)
    ledger = tmp_path / "l.jsonl"
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        ledger_path=ledger,
        event_bus=_SpyBus(),  # type: ignore[arg-type]
        judge_independence_enabled=False,  # flag OFF
        self_mod_fail_closed_enabled=False,  # flag OFF
        # Configured but MUST be ignored while the flag is off.
        independent_model="gpt-4o",
    )
    inp = PostVerifyInput(
        surface="pr_review", diff=_structural_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    assert result.verdict == "APPROVE"
    # Same-family dispatch — no independent routing while the flag is off.
    assert runner.calls[0]["model"] == "opus"
    # Inert: no ledger rows and no bus publishes on the flag-off success path.
    assert ji.read_records(ledger) == []
    assert published == []


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


# ---------------------------------------------------------------------------
# Advisory surface must NOT silently downgrade a self-mod fail-closed VETO.
#
# The advisory-authority downgrade block (``review_advisor.py`` ~724-731) turns
# a VETO into APPROVE for advisory surfaces. It runs ONLY on the parse-success
# path, AFTER the self-mod fail-closed / HITL branches have already early-
# returned their VETO. The no-downgrade property is therefore guaranteed by
# ordering alone — these tests fail if the downgrade block is ever moved above
# those early returns (which would silently pass a fail-closed STOP).
# ---------------------------------------------------------------------------


def test_advisory_surface_does_not_downgrade_self_mod_fail_closed_stop(
    tmp_path: Path,
):
    """Fail-open self-mod STOP on an advisory surface (wiki_ingest) stays VETO."""
    runner = _StubRunner(RuntimeError("judge unavailable"))
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
        ledger_path=tmp_path / "l.jsonl",
        self_mod_fail_closed_enabled=True,
    )
    # Premise guard: this surface is genuinely advisory, so the downgrade block
    # is "armed" — the test is meaningful only if a VETO here COULD be
    # downgraded on the success path.
    assert advisor._cfg.post_verify_authority == "advisory"
    inp = PostVerifyInput(
        surface="wiki_ingest", diff=_self_mod_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    # The self-mod fail-closed STOP survives the advisory surface.
    assert result.verdict == "VETO"
    fo = [
        r
        for r in ji.read_records(tmp_path / "l.jsonl")
        if r["kind"] == ji.KIND_FAIL_OPEN
    ]
    assert fo[0]["disposition"] == "fail_closed_stop"


def test_advisory_surface_does_not_downgrade_self_mod_hitl_escalation(
    tmp_path: Path,
):
    """Self-mod HITL escalation (no independent family + fail-closed) on an
    advisory surface stays VETO and never dispatches to the same-family judge."""
    runner = _StubRunner(_APPROVE)  # would APPROVE if it were ever dispatched
    advisor = PostVerifyAdvisor(
        runner=runner,
        surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
        ledger_path=tmp_path / "l.jsonl",
        judge_independence_enabled=True,
        self_mod_fail_closed_enabled=True,
        independent_model="",  # no independent family → self-mod escalates to HITL
    )
    assert advisor._cfg.post_verify_authority == "advisory"
    inp = PostVerifyInput(
        surface="wiki_ingest", diff=_self_mod_diff(), executor_verdict_summary="ok"
    )
    result = asyncio.run(advisor.run(inp))
    assert result.verdict == "VETO"
    assert "HITL" in result.reasoning
    assert runner.calls == []  # early return before dispatch and before downgrade
