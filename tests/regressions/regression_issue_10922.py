"""Regression for #10922: the convergence gate allows 3 fix rounds before HITL.

max_review_fix_attempts defaulted to 2, so a healthy convergence that needed a
third round after two that each fixed real findings was escalated to a human —
wasting the self-solve the gate exists to allow (observed on PR #10901). The
default is now 3.
"""

from __future__ import annotations

from pathlib import Path

from config import HydraFlowConfig


def test_default_review_fix_attempts_is_three(tmp_path: Path) -> None:
    cfg = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )
    assert cfg.max_review_fix_attempts == 3
