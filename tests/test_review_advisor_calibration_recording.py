"""Wiring tests: PostVerifyAdvisor → judge-calibration ledger (#10836).

The advisor best-effort records its RAW verdict + confidence for proper scoring.
Verifies the happy path writes a joinable record, that the raw call is recorded
even when advisory authority downgrades the returned verdict, that a missing
confidence is honestly skipped, and — load-bearing — that a ledger write error
NEVER propagates into the review pipeline.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from judge_calibration import (
    JudgeCalibrationLedger,
    Verdict,
    judge_verdict_ledger_path,
    subject_for_issue,
    subject_for_pr,
)
from review_advisor import (
    SURFACE_ADVISOR_CONFIGS,
    PostVerifyAdvisor,
    PostVerifyInput,
    PreFlightAdvisor,
    PreFlightInput,
)

_APPROVE = '{"verdict":"APPROVE","reasoning":"ok","disagreements":[],"confidence":0.9}'
_VETO = '{"verdict":"VETO","reasoning":"bad","disagreements":[],"confidence":0.75}'
_APPROVE_NO_CONF = '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'


class _StubRunner:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    async def run(
        self, *, model: str, subagent_type: str, prompt: str, role: str
    ) -> str:
        self.calls.append({"model": model, "role": role})
        return self._payload


def _unclassed_diff() -> str:
    p = "src/comment_formatter.py"
    return f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n"


def test_records_pass_verdict_with_confidence(tmp_path: Path) -> None:
    path = judge_verdict_ledger_path(tmp_path)
    advisor = PostVerifyAdvisor(
        runner=_StubRunner(_APPROVE),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        pr_number=42,
        judge_verdict_ledger_path=path,
    )
    inp = PostVerifyInput(
        surface="pr_review",
        diff=_unclassed_diff(),
        executor_verdict_summary="approved",
        lens="correctness",
    )
    asyncio.run(advisor.run(inp))

    records = JudgeCalibrationLedger(path).read_all()
    assert len(records) == 1
    rec = records[0]
    assert rec.judge_id == "post_verify:correctness"
    assert rec.judge_family == "review_advisor"
    assert rec.subject_id == "pr:42"
    assert rec.verdict is Verdict.PASS
    assert rec.confidence == 0.9


def test_records_raw_veto_even_when_downgraded(tmp_path: Path) -> None:
    # wiki_ingest is advisory authority: the returned verdict is downgraded to
    # APPROVE, but calibration must score the judge's RAW call (VETO → FAIL).
    path = judge_verdict_ledger_path(tmp_path)
    advisor = PostVerifyAdvisor(
        runner=_StubRunner(_VETO),
        surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
        pr_number=7,
        judge_verdict_ledger_path=path,
    )
    inp = PostVerifyInput(
        surface="wiki_ingest",
        diff=_unclassed_diff(),
        executor_verdict_summary="done",
    )
    result = asyncio.run(advisor.run(inp))

    assert result is not None
    assert result.verdict == "APPROVE"  # downgraded on return
    rec = JudgeCalibrationLedger(path).read_all()[0]
    assert rec.verdict is Verdict.FAIL  # raw call recorded
    assert rec.judge_id == "post_verify"  # no lens
    assert rec.confidence == 0.75


def test_missing_confidence_is_not_recorded(tmp_path: Path) -> None:
    path = judge_verdict_ledger_path(tmp_path)
    advisor = PostVerifyAdvisor(
        runner=_StubRunner(_APPROVE_NO_CONF),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        pr_number=42,
        judge_verdict_ledger_path=path,
    )
    inp = PostVerifyInput(
        surface="pr_review",
        diff=_unclassed_diff(),
        executor_verdict_summary="approved",
    )
    asyncio.run(advisor.run(inp))
    # No numeric confidence → honestly skipped, never fabricated.
    assert JudgeCalibrationLedger(path).read_all() == []


def test_no_ledger_path_disables_recording(tmp_path: Path) -> None:
    advisor = PostVerifyAdvisor(
        runner=_StubRunner(_APPROVE),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        pr_number=42,
        judge_verdict_ledger_path=None,
    )
    inp = PostVerifyInput(
        surface="pr_review",
        diff=_unclassed_diff(),
        executor_verdict_summary="approved",
    )
    # No ledger wired → runs clean, writes nothing anywhere.
    result = asyncio.run(advisor.run(inp))
    assert result is not None
    assert result.verdict == "APPROVE"


def test_ledger_write_error_never_propagates(tmp_path: Path) -> None:
    # Point the ledger at a path whose PARENT is a file, so mkdir/open raises.
    # The recorder must swallow it: the verdict returns intact.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")
    doomed_path = blocker / "calibration" / "judge_verdicts.jsonl"

    advisor = PostVerifyAdvisor(
        runner=_StubRunner(_APPROVE),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        pr_number=42,
        judge_verdict_ledger_path=doomed_path,
    )
    inp = PostVerifyInput(
        surface="pr_review",
        diff=_unclassed_diff(),
        executor_verdict_summary="approved",
    )
    result = asyncio.run(advisor.run(inp))

    assert result is not None
    assert result.verdict == "APPROVE"
    assert not doomed_path.exists()


# --- #10836 phase 2: PreFlightAdvisor → judge-calibration ledger -----------

_PLAN_WITH_FORECAST = (
    '{"risk_summary":"touches dispatch","focus_areas":[],"rubric":[],'
    '"escalation_signals":[],"defect_verdict":"FAIL","confidence":0.8}'
)
_PLAN_LEGACY_SHAPE = (
    '{"risk_summary":"touches dispatch","focus_areas":[],"rubric":[],'
    '"escalation_signals":[]}'
)


def _preflight_input() -> PreFlightInput:
    return PreFlightInput(surface="pr_review", diff=_unclassed_diff())


def test_preflight_records_forecast(tmp_path: Path) -> None:
    path = judge_verdict_ledger_path(tmp_path)
    advisor = PreFlightAdvisor(
        runner=_StubRunner(_PLAN_WITH_FORECAST),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        pr_number=42,
        judge_verdict_ledger_path=path,
        calibration_subject_id=subject_for_pr(42),
    )
    plan = asyncio.run(advisor.run(_preflight_input()))

    assert plan is not None
    records = JudgeCalibrationLedger(path).read_all()
    assert len(records) == 1
    rec = records[0]
    assert rec.judge_id == "pre_flight"
    assert rec.judge_family == "review_advisor"
    assert rec.subject_id == "pr:42"
    assert rec.verdict is Verdict.FAIL
    assert rec.confidence == 0.8


def test_preflight_issue_subject_join(tmp_path: Path) -> None:
    # The pre-PR path joins by issue — the construction site computes the
    # subject explicitly, so no pr-vs-issue precedence logic can misjoin.
    path = judge_verdict_ledger_path(tmp_path)
    advisor = PreFlightAdvisor(
        runner=_StubRunner(_PLAN_WITH_FORECAST),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        pr_number=7,
        judge_verdict_ledger_path=path,
        calibration_subject_id=subject_for_issue(7),
    )
    asyncio.run(advisor.run(_preflight_input()))

    assert JudgeCalibrationLedger(path).read_all()[0].subject_id == "issue:7"


def test_preflight_without_forecast_is_skipped(tmp_path: Path) -> None:
    # Legacy-shape plan (no defect_verdict/confidence): still a valid plan —
    # back-compat pinned — but nothing is recorded; absence is honest.
    path = judge_verdict_ledger_path(tmp_path)
    advisor = PreFlightAdvisor(
        runner=_StubRunner(_PLAN_LEGACY_SHAPE),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        pr_number=42,
        judge_verdict_ledger_path=path,
        calibration_subject_id=subject_for_pr(42),
    )
    plan = asyncio.run(advisor.run(_preflight_input()))

    assert plan is not None
    assert plan.risk_summary == "touches dispatch"
    assert JudgeCalibrationLedger(path).read_all() == []


def test_preflight_without_ledger_wiring_is_noop(tmp_path: Path) -> None:
    advisor = PreFlightAdvisor(
        runner=_StubRunner(_PLAN_WITH_FORECAST),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        pr_number=42,
    )
    plan = asyncio.run(advisor.run(_preflight_input()))

    assert plan is not None
    assert not judge_verdict_ledger_path(tmp_path).exists()


def test_preflight_prompt_elicits_forecast() -> None:
    advisor = PreFlightAdvisor(
        runner=_StubRunner(_PLAN_WITH_FORECAST),
        surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
    )
    prompt = advisor._build_prompt(_preflight_input())
    assert '"defect_verdict":"PASS"|"FAIL"' in prompt
    assert "calibrated self-estimate" in prompt
