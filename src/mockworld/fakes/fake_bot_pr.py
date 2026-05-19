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

    async def open_bot_pr(
        self,
        *,
        branch: str,
        title: str,
        body: str,
        labels: list[str],
        files: dict[str, str],
    ) -> int:
        """Record the call and return the next auto-incremented PR number."""
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
        return pr_number

    def reset(self) -> None:
        """Clear recorded calls and reset the PR counter to 1."""
        self.calls.clear()
        self.next_pr_number = 1
