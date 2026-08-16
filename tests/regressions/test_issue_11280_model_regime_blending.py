"""Regression tests for issue #11280 — model-regime blending across a
provider switch (the 2026-08-15 GLM/glm-5.2 fleet move).

Before the fix, every DERIVED telemetry surface aggregated across models per
source/loop even though raw telemetry attributes per (tool, model) correctly:

* `prompt_efficiency.compute_skill_efficiency` compared a source's current
  window cost-per-call against a baseline built under a DIFFERENT model —
  a pricing-regime change (e.g. claude -> glm-5.2) read as a fake
  improvement, and the eventual switch-back would file a fake regression
  (the exact false-positive class #11152 eliminated, reintroduced via
  pricing regime instead of denominators).
* `review_advisor`'s judge-calibration recorder hardcoded
  ``judge_family="review_advisor"`` regardless of which model was actually
  dispatched, so `judge_calibration.score_all()` pooled a claude-judge's
  Brier/ECE with a glm-judge's into one meaningless number.
* `dashboard_routes._cost_rollups.build_per_loop_cost`'s >2x cost-spike
  signal compared a blended $/tick average across periods with no model
  dimension, so a loop switching models read identically to a genuine cost
  regression.

The fix threads a (provider, model) "regime" dimension through exactly the
comparison point in each surface, without restructuring the underlying
cumulative storage. These tests exercise each surface's regime-mismatch path
end to end; the fuller matrices (regime match, unknown regime, back-compat)
live in `tests/test_prompt_efficiency.py`,
`tests/test_review_advisor_calibration_recording.py`, and
`tests/test_cost_rollups_helpers.py`.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import HydraFlowConfig
from dashboard_routes._cost_rollups import build_per_loop_cost
from judge_calibration import JudgeCalibrationLedger, judge_verdict_ledger_path
from prompt_efficiency import compute_skill_efficiency
from review_advisor import SURFACE_ADVISOR_CONFIGS, PostVerifyAdvisor, PostVerifyInput
from tests.helpers import ConfigFactory


def test_prompt_efficiency_baseline_reset_on_claude_to_glm_switch() -> None:
    """A source's baseline was built entirely under claude; the fleet then
    switches to glm-5.2 mid-week. The window/trend comparison must reset —
    NOT read the pricing-regime drop as a cost improvement."""
    baseline = {
        "diff-sanity": {
            "inference_calls": 100_000,
            "estimated_cost_microusd": 1_000_000_000,  # $0.01/call under claude
            "usage_unavailable_calls": 0,
        }
    }
    current = {
        "diff-sanity": {
            "inference_calls": 100_100,
            "estimated_cost_microusd": 100_000,  # cheap glm-5.2 calls
            "usage_unavailable_calls": 0,
        }
    }
    rows = compute_skill_efficiency(
        current,
        baseline=baseline,
        current_regimes={"diff-sanity": "glm-5.2"},
        baseline_regimes={"diff-sanity": "claude-sonnet-4-5"},
    )
    row = rows[0]
    assert row.regime_changed is True
    # The would-be "99.99% improvement" trend must be nulled, not reported.
    assert row.trend_vs_baseline is None


def _unclassed_diff() -> str:
    p = "src/comment_formatter.py"
    return f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n"


class _StubRunner:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.calls: list[dict[str, str]] = []

    async def run(self, *, model: str, subagent_type: str, prompt: str, role: str) -> str:
        self.calls.append(
            {"model": model, "subagent_type": subagent_type, "prompt": prompt, "role": role}
        )
        return self._payload


def test_judge_calibration_does_not_pool_claude_and_glm_judges(
    tmp_path: Path,
) -> None:
    """Two verdicts on the same lens, dispatched to claude then glm — the
    calibration ledger must record them under distinct judge_ids so
    `score_all()` never blends a claude-judge Brier/ECE with a glm-judge's."""
    path = judge_verdict_ledger_path(tmp_path)
    claude_cfg = SURFACE_ADVISOR_CONFIGS["pr_review"]
    glm_cfg = dataclasses.replace(claude_cfg, advisor_model="glm-5.2")
    approve = '{"verdict":"APPROVE","reasoning":"ok","disagreements":[],"confidence":0.9}'
    inp = PostVerifyInput(
        surface="pr_review",
        diff=_unclassed_diff(),
        executor_verdict_summary="approved",
    )

    for cfg in (claude_cfg, glm_cfg):
        advisor = PostVerifyAdvisor(
            runner=_StubRunner(approve),
            surface_config=cfg,
            pr_number=42,
            judge_verdict_ledger_path=path,
        )
        asyncio.run(advisor.run(inp))

    records = JudgeCalibrationLedger(path).read_all()
    assert {rec.judge_id for rec in records} == {"post_verify:claude", "post_verify:zhipu"}


def _write_inference(config: HydraFlowConfig, **fields: object) -> None:
    import json

    d = config.cost_inferences_path.parent
    d.mkdir(parents=True, exist_ok=True)
    with config.cost_inferences_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def test_per_loop_cost_spike_signal_distinguishes_model_switch_from_regression(
    tmp_path: Path,
) -> None:
    """A loop's dominant model switches from claude to glm-5.2 between the
    prior and current period — `model_regime_changed` must be set so a
    downstream cost-anomaly detector (or the dashboard's spike highlight)
    can tell 'loop changed models' apart from 'loop got expensive'."""
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    config = ConfigFactory.create(repo_root=tmp_path / "repo")

    now = datetime(2026, 8, 16, 12, tzinfo=UTC)
    since = now - timedelta(hours=1)
    prev_since = since - timedelta(hours=1)

    _write_inference(
        config,
        timestamp=(prev_since + timedelta(minutes=5)).isoformat(),
        source="implementer",
        model="claude-opus-4-7",
        input_tokens=1_000,
        output_tokens=200,
    )
    _write_inference(
        config,
        timestamp=(since + timedelta(minutes=5)).isoformat(),
        source="implementer",
        model="glm-5.2",
        input_tokens=1_000,
        output_tokens=200,
    )

    rows = build_per_loop_cost(config, since=since, until=now)

    assert len(rows) == 1
    assert rows[0]["model_regime_changed"] is True
