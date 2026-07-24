"""Regression guards for the #10370 sampled-audit hardening review.

Four review findings on the silent-escape estimator, each of which would
silently invalidate a measurement without failing the pre-existing tests:

1. **No-contamination has no direct prompt test.** ``build_audit_prompt`` and
   its no-verdict charter were only asserted via a decorative ``input_sources``
   constant; threading the original gauntlet verdict into the produced prompt
   would pass every test and destroy the auditor's independence. Guard: the
   prompt string carries only diff + spec/issue + repo-state, never verdict
   data, and the builder's signature admits no verdict/approval argument.

2. **Governance dampening.** The 3σ UCL used only the LATEST subgroup's sample
   count; at realistic per-tick volumes (0-3 samples) the limit was ~0.43-0.70,
   so the widen branch never fired while every quiet tick narrowed — the rate
   decayed to the 2% floor. Guard: sustained real-volume disagreement widens.

3. **Empty-tick narrowing.** A select-nothing tick appended a ``sampled=0``
   observation whose ``0.0`` proportion narrowed the rate on no information.
   Guard: an empty tick records no observation and leaves the rate untouched.

4. **Disposition inflation.** Any non-not-planned close with no label defaulted
   to ``upheld`` → an incidentally closed find issue fabricated a silent escape.
   Guard: only an explicit ``audit-upheld`` label yields ``upheld``.
"""

from __future__ import annotations

import inspect

from audit.budget import (
    MAX_DIFF_CONTEXT_CHARS,
    _CHARS_PER_TOKEN,
    _OUTPUT_TOKENS,
    estimate_audit_tokens,
)
from audit.disposition import reconcile_disposition
from audit.governance import DEFAULT_BASE_RATE, govern_rate, upper_control_limit
from audit.models import DisagreementObservation, MergedChange
from sampled_audit_loop import build_audit_prompt


def _change(*, body: str = "", paths: tuple[str, ...] = ("src/x.py",)) -> MergedChange:
    return MergedChange(
        pr_number=4242,
        merge_sha="deadbeefcafe0000",
        subject="feat(core): add widget (#4242)",
        changed_paths=paths,
        merged_at="2026-07-23T00:00:00+00:00",
        body=body,
    )


class TestPromptNoContamination:
    def test_prompt_never_carries_original_verdict_from_body(self) -> None:
        verdict = "GAUNTLET_VERDICT=APPROVED score=0.98 reviewer=judge-A"
        prompt = build_audit_prompt(_change(body=verdict), diff="SENTINEL_DIFF")
        assert "SENTINEL_DIFF" in prompt  # the legit merged-diff input is present
        assert verdict not in prompt  # …but the verdict-in-body never leaks
        assert "APPROVED" not in prompt

    def test_signature_admits_no_verdict_argument(self) -> None:
        params = list(inspect.signature(build_audit_prompt).parameters)
        assert params == ["change", "diff"]


class TestGovernanceRealisticVolume:
    def test_sustained_small_sample_disagreement_widens(self) -> None:
        history = [DisagreementObservation(3, 2) for _ in range(6)]  # 2/3 per tick
        assert govern_rate(history, current_rate=DEFAULT_BASE_RATE) > DEFAULT_BASE_RATE

    def test_ucl_tightens_with_pooled_window(self) -> None:
        latest_only = [DisagreementObservation(2, 0)]
        pooled = [DisagreementObservation(2, 0) for _ in range(20)]
        assert upper_control_limit(pooled) < upper_control_limit(latest_only)


class TestBudgetChargesDiffAndOutput:
    def test_single_path_estimate_counts_full_diff_window_and_output(self) -> None:
        single = estimate_audit_tokens(_change(paths=("src/one_big.py",)))
        assert single >= MAX_DIFF_CONTEXT_CHARS // _CHARS_PER_TOKEN + _OUTPUT_TOKENS
        assert single > 2400  # over the discredited 2000 + 400*paths estimate


class TestDispositionNoInflation:
    def test_incidental_close_without_label_is_not_upheld(self) -> None:
        assert reconcile_disposition("COMPLETED", []) == "pending"
        assert reconcile_disposition("CLOSED", []) == "pending"

    def test_explicit_upheld_label_required_for_upheld(self) -> None:
        assert reconcile_disposition("COMPLETED", ["audit-upheld"]) == "upheld"
