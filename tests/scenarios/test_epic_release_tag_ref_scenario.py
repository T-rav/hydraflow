"""MockWorld scenario for #11517 — an epic release tags the promoted ``main``.

Drives the real ``EpicCompletionChecker`` (ADR-0011) against ``FakeGitHub``
and the world's real ``StateTracker``:

1. A versioned epic whose children are all ``fixed`` completes through
   ``check_and_close_epics`` — the close path itself mints NO tag (release
   creation was decoupled from epic close in #2689; see
   ``tests/test_release.py::test_no_release_on_epic_close``).
2. The release primitive then records ``create_tag(tag, ref=<main sha>)``
   where ``<main sha>`` is what ``resolve_remote_branch_sha(main_branch)``
   returned — the promoted ``main`` per ADR-0042 — and persists the
   ``Release`` row.
3. An unversioned epic still skips the release entirely.
4. When ``origin/<main>`` cannot be resolved the release is skipped
   fail-closed: no tag, no release, no state row.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_MAIN_SHA = "9f2c0d4e8b7a6c5d4e3f2a1b0c9d8e7f6a5b4c3d"
_EPIC = 11517
_CHILDREN = (11518, 11519)
_VERSIONED_TITLE = "[Epic] v1.0.0 — stable base"
_UNVERSIONED_TITLE = "[Epic] Stabilise the docs"


def _issue_fetcher(world: MockWorld) -> MagicMock:
    """``IssueFetcher`` adapter reading live from ``world.github``."""
    from models import GitHubIssue, GitHubIssueState  # noqa: PLC0415

    def _to_gh(fake: Any) -> GitHubIssue:
        return GitHubIssue(
            number=fake.number,
            title=fake.title,
            body=fake.body,
            labels=list(fake.labels),
            state=GitHubIssueState(fake.state),
        )

    async def _by_labels(labels: Any, limit: int = 50, **_kw: Any) -> list[GitHubIssue]:
        wanted = set(labels) if isinstance(labels, list | tuple | set) else {labels}
        return [
            _to_gh(fi)
            for fi in world.github._issues.values()
            if fi.state == "open" and wanted & set(fi.labels)
        ][:limit]

    async def _by_number(number: int) -> GitHubIssue | None:
        fi = world.github._issues.get(number)
        return _to_gh(fi) if fi is not None else None

    fetcher = MagicMock()
    fetcher.fetch_issues_by_labels = AsyncMock(side_effect=_by_labels)
    fetcher.fetch_issue_by_number = AsyncMock(side_effect=_by_number)
    return fetcher


def _seed_epic(world: MockWorld, title: str) -> None:
    config = world.harness.config
    body = "\n".join(f"- [ ] #{c} — child {c}" for c in _CHILDREN)
    world.add_issue(_EPIC, title, body, labels=[config.epic_label[0]])
    for child in _CHILDREN:
        world.add_issue(child, f"child {child}", "", labels=[config.fixed_label[0]])


def _make_checker(world: MockWorld) -> Any:
    from epic import EpicCompletionChecker  # noqa: PLC0415

    return EpicCompletionChecker(
        world.harness.config,
        world.github,  # type: ignore[arg-type]
        _issue_fetcher(world),
        state=world.harness.state,
    )


async def test_versioned_epic_completes_and_release_tags_promoted_main(tmp_path):
    world = MockWorld(tmp_path)
    _seed_epic(world, _VERSIONED_TITLE)
    world.github.set_branch_head(world.harness.config.main_branch, _MAIN_SHA)
    checker = _make_checker(world)

    closed = await checker.check_and_close_epics(_CHILDREN[0])

    assert closed is True
    assert world.github.issue(_EPIC).state == "closed"
    assert world.github.tags == {}, "epic close must not mint a tag (#2689)"

    url, _changelog = await checker._create_release_for_epic(
        _EPIC, _VERSIONED_TITLE, list(_CHILDREN)
    )

    assert url.endswith("/releases/tag/v1.0.0")
    assert world.github.tags == {"v1.0.0": _MAIN_SHA}
    assert world.github.releases["v1.0.0"][0] == "Release v1.0.0"
    release = world.harness.state.get_release(_EPIC)
    assert release is not None
    assert (release.tag, release.version, release.status) == (
        "v1.0.0",
        "1.0.0",
        "released",
    )


async def test_unversioned_epic_skips_release(tmp_path):
    world = MockWorld(tmp_path)
    _seed_epic(world, _UNVERSIONED_TITLE)
    world.github.set_branch_head(world.harness.config.main_branch, _MAIN_SHA)
    checker = _make_checker(world)

    assert await checker.check_and_close_epics(_CHILDREN[0]) is True
    url, changelog = await checker._create_release_for_epic(
        _EPIC, _UNVERSIONED_TITLE, list(_CHILDREN)
    )

    assert (url, changelog) == ("", "")
    assert world.github.tags == {}
    assert world.github.releases == {}
    assert world.harness.state.get_release(_EPIC) is None


async def test_unresolvable_main_skips_release_fail_closed(tmp_path):
    world = MockWorld(tmp_path)
    _seed_epic(world, _VERSIONED_TITLE)
    world.github.set_branch_head(world.harness.config.main_branch, None)
    checker = _make_checker(world)

    url, _changelog = await checker._create_release_for_epic(
        _EPIC, _VERSIONED_TITLE, list(_CHILDREN)
    )

    assert url == ""
    assert world.github.tags == {}, "must never fall back to tagging HEAD"
    assert world.github.releases == {}
    assert world.harness.state.get_release(_EPIC) is None
