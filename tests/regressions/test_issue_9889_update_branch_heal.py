"""Shepherd heal class 2: update-branch for CI-failed bot PRs (#9889).

Re-running failed jobs pins the OLD merge ref (the #9884 lesson) — a bot PR
red on state the base already fixed (baseline advances, sibling regens)
stayed red forever under retry. One bounded update-branch forces a fresh
merge ref and a full CI re-run before the failure strategy applies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_dependabot_merge_loop import _make_loop, _make_pr


@pytest.mark.asyncio
async def test_ci_failed_pr_gets_update_branch_before_strategy(
    tmp_path: Path,
) -> None:
    loop, _, _, prs, state = _make_loop(
        tmp_path,
        open_prs=[_make_pr(9884, author="hydraflow-ul-bot", branch="ul-x")],
        ci_result=(False, "Failed checks: Principles Audit"),
        failure_strategy="hitl",
        authors=["hydraflow-ul-bot"],
        update_branch_max_attempts=1,
    )

    result = await loop._do_work()

    prs.update_pr_branch.assert_awaited_once_with(9884, method="merge")
    state.bump_dependabot_update_branch_attempts.assert_called_once_with(9884)
    assert result["skipped"] == 1
    assert result["failed"] == 0
    prs.add_labels.assert_not_awaited()  # no strategy side effects


@pytest.mark.asyncio
async def test_cap_reached_falls_through_to_strategy(tmp_path: Path) -> None:
    loop, _, _, prs, state = _make_loop(
        tmp_path,
        open_prs=[_make_pr(9885, author="hydraflow-ul-bot", branch="ul-y")],
        ci_result=(False, "Failed checks: Tests"),
        failure_strategy="hitl",
        authors=["hydraflow-ul-bot"],
        update_branch_max_attempts=1,
    )
    state.get_dependabot_update_branch_attempts.side_effect = lambda _n: 1

    result = await loop._do_work()

    prs.update_pr_branch.assert_not_awaited()
    assert result["failed"] == 1  # hitl strategy applied
    prs.add_labels.assert_awaited_once()


@pytest.mark.asyncio
async def test_already_up_to_date_falls_through_without_burning_budget(
    tmp_path: Path,
) -> None:
    loop, _, _, prs, state = _make_loop(
        tmp_path,
        open_prs=[_make_pr(9886, author="hydraflow-ul-bot", branch="ul-z")],
        ci_result=(False, "Failed checks: Tests"),
        failure_strategy="skip",
        authors=["hydraflow-ul-bot"],
        update_branch_max_attempts=1,
        update_branch_result=False,  # GitHub: already up to date / refused
    )

    result = await loop._do_work()

    prs.update_pr_branch.assert_awaited_once()
    state.bump_dependabot_update_branch_attempts.assert_not_called()
    assert result["skipped"] == 1  # skip strategy, budget intact


@pytest.mark.asyncio
async def test_kill_switch_zero_disables_heal(tmp_path: Path) -> None:
    loop, _, _, prs, _ = _make_loop(
        tmp_path,
        open_prs=[_make_pr(9887, author="hydraflow-ul-bot", branch="ul-w")],
        ci_result=(False, "Failed checks: Tests"),
        failure_strategy="skip",
        authors=["hydraflow-ul-bot"],
        update_branch_max_attempts=0,
    )

    await loop._do_work()

    prs.update_pr_branch.assert_not_awaited()
