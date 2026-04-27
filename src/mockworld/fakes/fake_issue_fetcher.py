"""FakeIssueFetcher — IssueFetcherPort impl backed by FakeGitHub state.

Standalone class created for the sandbox entrypoint (Task 1.10), which
constructs Fakes via build_services() overrides — monkeypatching only
works in-process and can't reach the docker container.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed

    from mockworld.fakes.fake_github import FakeGitHub


@dataclass
class FakeIssueSummary:
    """Minimal IssueFetcher-shaped payload."""

    number: int
    title: str
    body: str
    labels: list[str]
    state: str = "OPEN"


class FakeIssueFetcher:
    """Minimal sandbox stand-in — does NOT satisfy IssueFetcherPort.

    Provides only `fetch_open_issues_by_label` — the surface the sandbox
    entrypoint needs (Task 1.10). The real IssueFetcherPort has additional
    methods (`fetch_issue_by_number`, `fetch_issues_by_labels`). Extend
    here when sandbox scenarios need more methods. Do NOT pass this where
    an IssueFetcherPort is required without checking the call site.
    """

    _is_fake_adapter = True

    def __init__(self, github: FakeGitHub) -> None:
        self._github = github

    @classmethod
    def from_seed(cls, seed: MockWorldSeed) -> FakeIssueFetcher:
        """Build a FakeIssueFetcher from a serialized seed.

        Constructs an internal FakeGitHub from the seed's issue list
        and wraps it. Same semantics as constructing FakeGitHub.from_seed
        and passing it in. (FakeGitHub.from_seed lands in Task 1.6.)
        """
        from mockworld.fakes.fake_github import FakeGitHub

        # TASK 1.6 MIGRATION: when FakeGitHub.from_seed lands, replace these
        # 6 lines with `github = FakeGitHub.from_seed(seed)`. Same change
        # required in fake_issue_store.py:from_seed (sister file).
        github = FakeGitHub()
        for issue_dict in seed.issues:
            github.add_issue(
                number=issue_dict["number"],
                title=issue_dict["title"],
                body=issue_dict["body"],
                labels=list(issue_dict.get("labels", [])),
            )
        return cls(github=github)

    async def fetch_open_issues_by_label(self, label: str) -> list[FakeIssueSummary]:
        out = []
        for issue in self._github._issues.values():
            if issue.state != "open":
                continue
            if label not in issue.labels:
                continue
            out.append(
                FakeIssueSummary(
                    number=issue.number,
                    title=issue.title,
                    body=issue.body,
                    labels=list(issue.labels),
                )
            )
        return out
