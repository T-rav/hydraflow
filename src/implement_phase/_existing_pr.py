"""Finding a PR that already closes an issue, whatever its branch is called.

The pre-implementation check predicted a head branch of ``agent/issue-{N}`` and
asked for an open PR by literal branch-name equality. That is the shape the
FACTORY's own runner creates; anything opened by a human, or by an agent working
in a worktree, uses a conventional-commit branch name — which is most of what
merges. A complete PR under `fix/{N}-slug` was invisible, so the auto-agent
re-implemented work that already existed (#11981).

The declaration is the evidence, not the branch name. A PR says what it closes
in its title or body with a closing keyword, and `false_close.closing_issue_refs`
already parses exactly that — the same predicate P10.7 uses to detect false
closes, so the two cannot drift apart.

Deliberately no new read. `list_all_open_prs` already exists and the Port
documents reusing it "instead of adding a new read" (#10027); bodies are fetched
only for the PRs that survive the cheap checks, and only up to a cap, so a repo
with hundreds of open PRs cannot turn one pre-flight into hundreds of API calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from false_close import closing_issue_refs

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Awaitable, Callable

    from models import PRListItem

#: How many candidate bodies one pre-flight may read. Small on purpose: this is
#: a courtesy check that prevents duplicate work, not a gate, so it must never
#: cost more than the work it saves. Beyond the cap the check simply does not
#: find anything, which is exactly the behaviour it had before this existed.
_MAX_BODY_READS = 25


async def find_open_pr_declaring(
    issue_number: int,
    *,
    list_open_prs: Callable[[], Awaitable[list[PRListItem]]],
    read_title_and_body: Callable[[int], Awaitable[tuple[str, str]]],
) -> int | None:
    """The number of an open PR declaring it closes *issue_number*, or None.

    Two passes, cheapest first. `PRListItem.issue` is derived from the branch
    name, so it answers for the factory's own PRs without any extra read; only
    when that misses does this pay for a body.

    Read failures are skipped rather than raised: this runs before
    implementation and its worst outcome is doing work that already exists.
    Failing the whole phase because one PR body was unreadable would trade a
    duplicate for an outage.
    """
    try:
        candidates = await list_open_prs()
    except (RuntimeError, OSError):
        return None

    for item in candidates:
        if item.issue == issue_number and item.pr > 0:
            return item.pr

    reads = 0
    for item in candidates:
        if item.pr <= 0 or reads >= _MAX_BODY_READS:
            continue
        reads += 1
        try:
            title, body = await read_title_and_body(item.pr)
        except (RuntimeError, OSError):
            continue
        if issue_number in closing_issue_refs(f"{title}\n{body}"):
            return item.pr
    return None
