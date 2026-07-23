"""Regression pins for #10358: the close-verification controller's hard constraints.

The G3 actuator reopens + re-triages an issue a merged PR closed without a fix
delta (the #10223 false-close signature). Two invariants are load-bearing and
must never silently regress:

1. **Default-OFF and fully inert.** With the flag off the controller must make
   NO port calls and change no behaviour — the same rollout discipline as the
   G1 auto-recut actuator. A refactor that reads the diff before the flag check
   would break the "changes nothing until enabled" contract.
2. **Never reopen a legitimate close.** A fix-delta close or a
   ``Skip-Regression:`` close must be left untouched, using the exact same
   signature the P10.7 detector uses (reused, not reimplemented).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from close_verification import reconcile_false_close
from config import HydraFlowConfig
from mockworld.fakes.fake_github import FakeGitHub
from ports import PRPort


def _cfg(tmp_path: Path, *, enabled: bool) -> HydraFlowConfig:
    return HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", close_verification_enabled=enabled
    )


def test_default_off_flag_makes_no_port_calls(tmp_path: Path) -> None:
    """Default is False and the disabled path never touches the port."""
    import asyncio

    # Ships default-OFF: a fresh config must not have the actuator armed.
    assert HydraFlowConfig(data_root=tmp_path).close_verification_enabled is False

    spy: PRPort = AsyncMock(spec=PRPort)
    result = asyncio.run(
        reconcile_false_close(
            config=_cfg(tmp_path, enabled=False),
            prs=spy,
            issue_number=42,
            pr_number=1042,
        )
    )
    assert result.actuated is False
    assert result.reason == "disabled"
    for method in ("get_pr_diff_names", "get_pr_commit_messages", "reopen_issue"):
        getattr(spy, method).assert_not_awaited()


def test_skip_regression_close_is_never_reopened(tmp_path: Path) -> None:
    """A Skip-Regression: opt-out close stays closed even with the flag on."""
    import asyncio

    gh = FakeGitHub()
    gh.add_issue(42, "t", "b", labels=["hydraflow-fixed"])
    gh._issues[42].state = "closed"
    gh.add_pr(number=1042, issue_number=42, branch="fix/42", merged=True)
    gh.set_pr_diff_names(1042, ["docs/x.md"])
    gh.set_pr_commit_messages(1042, "docs\n\nCloses #42\n\nSkip-Regression: elsewhere")

    result = asyncio.run(
        reconcile_false_close(
            config=_cfg(tmp_path, enabled=True),
            prs=gh,
            issue_number=42,
            pr_number=1042,
        )
    )
    assert result.actuated is False
    assert result.reason == "skip-regression"
    assert gh._issues[42].state == "closed"
