"""Regression: the two verdict classes stay distinct and correctly bound.

`JudgeVerdict` named two different concepts until #11782 — a gate's approval
(`convergence_gate.JudgeVerdict`: approve/feedback/signatures) and the
verification judge's evaluation (`models.JudgeVerdict`: issue_number/
criteria_results/...). `docs/wiki/terms/verdict.md` anchors the gate one, so
the other was renamed `VerificationJudgeVerdict`.

The danger in that rename was not the rename. `test_review_phase_core.py` uses
BOTH classes: the models one at module scope, the gate one via function-local
imports that SHADOW it. A blanket search-and-replace would have silently
rebound three gate-verdict constructions to the wrong class **and still
compiled** — the failure would surface as a confusing TypeError deep in a
review flow, or not at all if the fields happened to line up.

So this pins the shapes, not the names: each class must accept its own
constructor kwargs and reject the other's.
"""

from __future__ import annotations

import pytest

from convergence_gate import JudgeVerdict
from models import VerificationJudgeVerdict


def test_the_gate_verdict_carries_an_approval() -> None:
    verdict = JudgeVerdict(approve=True, feedback=None, signatures=["correctness"])

    assert verdict.approve is True
    assert verdict.signatures == ["correctness"]


def test_the_verification_verdict_carries_an_issue_evaluation() -> None:
    verdict = VerificationJudgeVerdict(issue_number=42)

    assert verdict.issue_number == 42
    assert verdict.all_criteria_pass is False


def test_the_two_are_not_the_same_class() -> None:
    """The whole point. If a future edit re-merges them this fails first."""
    assert JudgeVerdict is not VerificationJudgeVerdict


def test_a_gate_verdict_rejects_the_verification_shape() -> None:
    """Catches a rebind: if a gate call site were pointed at the models class
    (or vice versa) the kwargs would not fit, and this says so by name."""
    with pytest.raises(TypeError):
        JudgeVerdict(issue_number=42)  # type: ignore[call-arg]


def test_the_verification_verdict_does_not_accept_an_approval() -> None:
    with pytest.raises(Exception, match="approve"):
        VerificationJudgeVerdict(approve=True)  # type: ignore[call-arg]
