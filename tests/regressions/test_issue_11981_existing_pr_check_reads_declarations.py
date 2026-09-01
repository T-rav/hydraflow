"""#11981 — the pre-implementation PR check only knew one branch name.

`_flow_decompose` asked `find_open_pr_for_branch("agent/issue-{N}")`. That is
the shape the FACTORY's own runner creates; a PR opened by a human, or by an
agent working in a worktree, uses a conventional-commit branch name — which is
most of what merges. A complete PR under `fix/{N}-slug` was invisible, so the
auto-agent re-implemented work that already existed.

The declaration is the evidence, not the branch name. `closing_issue_refs` is
the same predicate P10.7 uses to detect false closes, so the two cannot drift.

Sibling of #11986, which is the same blindness in `get_pr_for_issue` and makes
the changelog record PR 0.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from implement_phase._existing_pr import _MAX_BODY_READS, find_open_pr_declaring
from models import PRListItem


def _items(*specs: tuple[int, int, str]) -> list[PRListItem]:
    return [
        PRListItem(pr=pr, issue=issue, branch=branch, title="a title")
        for pr, issue, branch in specs
    ]


async def _find(issue: int, items, bodies: dict[int, tuple[str, str]]):
    async def list_open_prs():
        return items

    async def read(pr: int):
        return bodies.get(pr, ("", ""))

    return await find_open_pr_declaring(
        issue, list_open_prs=list_open_prs, read_title_and_body=read
    )


class TestTheCheapPathStillWorks:
    @pytest.mark.asyncio
    async def test_a_factory_branch_resolves_without_reading_a_body(self) -> None:
        read = AsyncMock()

        async def list_open_prs():
            return _items((99, 4242, "agent/issue-4242"))

        found = await find_open_pr_declaring(
            4242, list_open_prs=list_open_prs, read_title_and_body=read
        )

        assert found == 99
        read.assert_not_awaited()


class TestTheDeclarationIsTheEvidence:
    @pytest.mark.asyncio
    async def test_a_conventional_branch_is_found_by_what_it_closes(self) -> None:
        found = await _find(
            11938,
            _items((99, 0, "fix/11938-config-mock-optional-numerics")),
            {99: ("fix(tests): decide numeric by walking", "Closes #11938")},
        )

        assert found == 99

    @pytest.mark.asyncio
    async def test_a_closing_keyword_in_the_title_counts(self) -> None:
        found = await _find(
            77, _items((5, 0, "some/branch")), {5: ("Fixes #77: the thing", "")}
        )

        assert found == 5

    @pytest.mark.asyncio
    async def test_a_bare_mention_is_not_a_declaration(self) -> None:
        # The decoy. "related to #77" is not a promise to close it, and
        # treating it as one would skip implementing an open issue.
        found = await _find(
            77, _items((5, 0, "some/branch")), {5: ("a title", "related to #77")}
        )

        assert found is None

    @pytest.mark.asyncio
    async def test_another_issues_pr_is_not_returned(self) -> None:
        found = await _find(
            77, _items((5, 0, "some/branch")), {5: ("t", "Closes #78")}
        )

        assert found is None


class TestItCostsLessThanTheWorkItSaves:
    @pytest.mark.asyncio
    async def test_body_reads_are_capped(self) -> None:
        """A courtesy check must never cost more than the duplicate it avoids."""
        items = _items(*[(n, 0, f"b/{n}") for n in range(1, _MAX_BODY_READS + 20)])
        reads: list[int] = []

        async def list_open_prs():
            return items

        async def read(pr: int):
            reads.append(pr)
            return ("", "")

        await find_open_pr_declaring(
            999, list_open_prs=list_open_prs, read_title_and_body=read
        )

        assert len(reads) == _MAX_BODY_READS

    @pytest.mark.asyncio
    async def test_an_unreadable_body_is_skipped_not_raised(self) -> None:
        # This runs BEFORE implementation. Failing the phase because one PR
        # body was unreadable would trade a duplicate for an outage.
        async def list_open_prs():
            return _items((5, 0, "a"), (6, 0, "b"))

        async def read(pr: int):
            if pr == 5:
                raise RuntimeError("gh down")
            return ("t", "Closes #77")

        found = await find_open_pr_declaring(
            77, list_open_prs=list_open_prs, read_title_and_body=read
        )

        assert found == 6

    @pytest.mark.asyncio
    async def test_an_unreadable_listing_finds_nothing(self) -> None:
        async def list_open_prs():
            raise RuntimeError("gh down")

        assert (
            await find_open_pr_declaring(
                77, list_open_prs=list_open_prs, read_title_and_body=AsyncMock()
            )
            is None
        )


class TestTheFlowActuallyConsultsIt:
    """The call site. Pinning the helper alone leaves the wiring unguarded."""

    @staticmethod
    async def _existing(branch_hit, declared_pr: int | None):
        from implement_phase._flow import ImplementFlowMixin

        phase = MagicMock(spec=ImplementFlowMixin)
        phase._prs = MagicMock()
        phase._prs.find_open_pr_for_branch = AsyncMock(return_value=branch_hit)
        phase._prs.list_all_open_prs = AsyncMock(
            return_value=_items((declared_pr or 0, 0, "fix/77-slug"))
            if declared_pr
            else []
        )
        phase._prs.get_pr_title_and_body = AsyncMock(return_value=("t", "Closes #77"))
        return await ImplementFlowMixin._existing_open_pr(phase, 77, "agent/issue-77")

    @pytest.mark.asyncio
    async def test_a_declared_pr_is_returned_when_the_branch_check_misses(
        self,
    ) -> None:
        found = await self._existing(None, 5)

        assert found is not None
        assert found.number == 5

    @pytest.mark.asyncio
    async def test_nothing_is_invented_when_no_pr_declares_the_issue(self) -> None:
        # The decoy: a fallback that returned something regardless would skip
        # implementation for every issue, forever.
        assert await self._existing(None, None) is None
