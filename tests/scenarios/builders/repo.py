"""RepoStateBuilder — composites issues + PRs into a whole-repo starting state."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from tests.scenarios.builders.issue import IssueBuilder
from tests.scenarios.builders.pr import PRBuilder

if TYPE_CHECKING:
    from tests.scenarios.fakes.mock_world import MockWorld


@dataclass(frozen=True)
class RepoStateBuilder:
    _issues: tuple[IssueBuilder, ...] = field(default_factory=tuple)
    _prs: tuple[PRBuilder, ...] = field(default_factory=tuple)

    def with_issues(self, issues: list[IssueBuilder]) -> RepoStateBuilder:
        return replace(self, _issues=tuple(issues))

    def with_prs(self, prs: list[PRBuilder]) -> RepoStateBuilder:
        return replace(self, _prs=tuple(prs))

    async def at(self, world: MockWorld) -> None:
        for issue in self._issues:
            issue.at(world)
        for pr in self._prs:
            await pr.at(world)
