"""Scenario-catalog dependabot_state must back the update-branch counter.

Surfaced by the staging->main RC promotion (#10276), which failed the
required `Browser Scenarios` check on::

    test_l8_dependabot_merge_skips_red_pr
    TypeError: '<' not supported between instances of 'MagicMock' and 'int'

Root cause: ``tests/scenarios/catalog/loop_registrations._build_dependabot_merge``
dict-backs the arch-refresh attempt counter (so ``get < cap`` behaves like the
real StateTracker) but never the *sibling* update-branch counter added by the
#9889 heal path. Under DEFAULT config (``dependabot_update_branch_max_attempts``
= 1, heal enabled) a CI-failed bot PR reaches
``dependabot_merge_loop.py`` line 481::

    self._state.get_dependabot_update_branch_attempts(pr.pr) < ub_cap

which read a bare ``MagicMock`` and raised ``TypeError``. The non-browser
reference (``TestL8DependabotMergeSkipsOnFailure``) masks the gap by pinning
``HYDRAFLOW_DEPENDABOT_UPDATE_BRANCH_MAX_ATTEMPTS=0`` — so the crash only
appeared where the heal path runs on default config. ``Browser Scenarios`` is
advisory on ``staging`` (ADR-0042) and required only on the ``main`` RC
promotion, so the red slipped through until the RC cut.

This test exercises the SAME registration with DEFAULT config (heal enabled) so
the fake-fidelity gap fails here, at unit speed, next to the fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld


@pytest.mark.asyncio
async def test_ci_failed_bot_pr_skips_with_update_branch_heal_enabled(
    tmp_path: Path,
) -> None:
    # NOTE: deliberately NO HYDRAFLOW_DEPENDABOT_UPDATE_BRANCH_MAX_ATTEMPTS pin —
    # default config keeps the #9889 update-branch heal path live, which is the
    # path that reads the update-branch attempt counter (line 481).
    from mockworld.fakes.fake_github import FakePR
    from models import PRListItem

    world = MockWorld(tmp_path)

    bot_pr = PRListItem(
        pr=600,
        title="Bump axios",
        author="dependabot[bot]",
        branch="dependabot/axios",
    )
    world.github._prs[600] = FakePR(
        number=600, issue_number=0, branch="dependabot/axios"
    )
    world.github.script_ci(600, [(False, "CI failed: test suite")])

    # First run initialises the loop's cache/state mock refs.
    await world.run_with_loops(["dependabot_merge"], cycles=1)
    world._dependabot_cache.get_open_prs.return_value = [bot_pr]
    world._dependabot_cache.get_all_open_prs.return_value = [bot_pr]

    # Before the fix this raised: '<' not supported between 'MagicMock' and 'int'.
    stats = await world.run_with_loops(["dependabot_merge"], cycles=1)

    assert stats is not None
    assert stats["dependabot_merge"]["skipped"] == 1
    assert stats["dependabot_merge"]["merged"] == 0
    assert world.github.pr(600).merged is False
