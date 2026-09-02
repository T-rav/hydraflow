"""MockWorld scenario: the unsticker's standing grant has a scope (#11970).

Pattern B (direct instantiation), like `test_memory_backlog_scenario.py`: the
unsticker needs a real `PRUnsticker` wired to `FakeGitHub`, because the defect
is that a PR gets MERGED and the loop-level registration in `test_loops.py`
mocks `unstick` wholesale.

Unit tests see the scope predicate and the branch it guards. Only this layer
sees the thing a reader of the running system cares about: whether the PR is
merged on the fake board afterwards.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.scenario_loops

_ISSUE = 4242
_PR = 99


def _unsticker(tmp_path: Path):
    from mockworld.fakes.fake_github import FakeGitHub  # noqa: PLC0415
    from pr_unsticker import PRUnsticker  # noqa: PLC0415
    from tests.conftest import make_state  # noqa: PLC0415
    from tests.helpers import ConfigFactory  # noqa: PLC0415

    config = ConfigFactory.create(repo_root=tmp_path)
    github = FakeGitHub()
    resolver = AsyncMock()
    resolver.save_conflict_transcript = MagicMock()

    unsticker = PRUnsticker(
        config,
        make_state(tmp_path),
        AsyncMock(),
        github,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        hitl_runner=AsyncMock(),
        stop_event=asyncio.Event(),
        resolver=resolver,
    )
    return unsticker, github


async def _merge_with_diff(tmp_path: Path, changed: list[str]):
    from tests.test_pr_unsticker import _make_hitl_item  # noqa: PLC0415

    unsticker, github = _unsticker(tmp_path)
    github.set_pr_diff_names(_PR, changed)
    merged = await unsticker._wait_and_merge(_make_hitl_item(issue=_ISSUE, pr=_PR))
    return merged, github


class TestTheStandingGrantHasAScope:
    async def test_a_pr_that_rewrites_the_rules_is_not_merged(
        self, tmp_path: Path
    ) -> None:
        merged, github = await _merge_with_diff(
            tmp_path, ["src/foo.py", "docs/standards/testing/README.md"]
        )

        assert merged is False

    async def test_a_mechanical_pr_still_merges(self, tmp_path: Path) -> None:
        # The decoy. A lane that merged nothing would satisfy the test above
        # while silently disabling the loop the issue exists to keep working.
        merged, github = await _merge_with_diff(tmp_path, ["src/foo.py"])

        assert merged is True
