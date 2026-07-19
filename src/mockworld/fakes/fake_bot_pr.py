"""FakeBotPR — in-memory BotPRPort for scenario and unit tests.

Implements ``BotPRPort`` (defined in ``term_proposer_loop``), which is the
minimal async interface for opening bot PRs. Used by TermProposerLoop,
TermPrunerLoop, and EdgeProposerLoop.

The Fake records every ``open_bot_pr`` call so tests can assert on which
branches and files were submitted without hitting git or the GitHub API.
A configurable ``next_pr_number`` seed lets tests set deterministic PR numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class OpenBotPRCall:
    """One captured ``open_bot_pr`` invocation."""

    branch: str
    title: str
    body: str
    labels: list[str]
    files: dict[str, str]


@dataclass
class FakeBotPR:
    """In-memory BotPRPort satisfying the Protocol from ``term_proposer_loop``.

    Records every ``open_bot_pr`` call in ``.calls``.  Returns sequentially
    incrementing PR numbers starting from ``next_pr_number`` (default 1).

    Usage in tests::

        fake = FakeBotPR()
        loop = TermProposerLoop(..., pr_port=fake)
        await loop.tick()
        assert len(fake.calls) == 1
        assert fake.calls[0].branch.startswith("ul-propose-")
    """

    _is_fake_adapter: ClassVar[bool] = True

    next_pr_number: int = 1
    calls: list[OpenBotPRCall] = field(default_factory=list)
    open_pr_labels: dict[int, list[str]] = field(default_factory=dict)
    find_queries: int = 0

    async def open_bot_pr(
        self,
        *,
        branch: str,
        title: str,
        body: str,
        labels: list[str],
        files: dict[str, str],
    ) -> int:
        """Record the call and return the next auto-incremented PR number.

        The PR is also registered as OPEN (``open_pr_labels``) so the
        single-flight guard (``find_open_bot_pr``, #9893) sees it on
        subsequent ticks. Tests close it with :meth:`close_pr`.
        """
        self.calls.append(
            OpenBotPRCall(
                branch=branch,
                title=title,
                body=body,
                labels=list(labels),
                files=dict(files),
            )
        )
        pr_number = self.next_pr_number
        self.next_pr_number += 1
        self.open_pr_labels[pr_number] = list(labels)
        return pr_number

    async def find_open_bot_pr(self, *, labels: list[str]) -> int | None:
        """Newest open bot PR carrying ANY of *labels*, or None (#9893)."""
        self.find_queries += 1
        wanted = set(labels)
        hits = [
            number
            for number, pr_labels in self.open_pr_labels.items()
            if wanted & set(pr_labels)
        ]
        return max(hits) if hits else None

    def close_pr(self, number: int) -> None:
        """Mark *number* closed/merged so the single-flight guard releases."""
        self.open_pr_labels.pop(number, None)

    def reset(self) -> None:
        """Clear recorded calls, open-PR state, and reset the PR counter to 1."""
        self.calls.clear()
        self.open_pr_labels.clear()
        self.find_queries = 0
        self.next_pr_number = 1
