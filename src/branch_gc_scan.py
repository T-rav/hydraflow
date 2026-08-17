"""Pure scan/classify engine for stale agent-branch GC (#10011).

The 2026-07-19 groom found 9+ unmerged ``origin/agent/issue-*`` /
``origin/fix/*`` branches carrying ``Fixes #N`` commits, with issue comments
claiming "fix applied" that were FALSE against staging — three issues
(#9553, #9554, #9661) were nearly wrongly closed on that evidence. Separately,
a FINISHED fix (regression collection, later PR #9965) sat
committed-but-unpushed on a local branch overnight, invisible to the
factory.

This module has two independent halves, both pure (no ``gh``/``git``
subprocess calls, no I/O beyond the strings/values handed in):

- **Remote branch reconciliation** — :func:`extract_issue_number` +
  :func:`classify_branch` decide, for one inventoried branch, whether
  ``StaleIssueLoop`` should post a "treat prior fix-applied claims as
  unverified" truth comment on the referenced issue, and
  :func:`should_delete_branch` separately gates the destructive
  delete-or-escalate step.
- **Local unpushed-work detection** — :func:`parse_unpushed_branches` reads
  ``git for-each-ref --format='%(refname:short)|%(upstream:short)|
  %(upstream:track)'`` output and reports local branches with commits not
  yet pushed to their upstream tracking branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# `Fixes #N` / `Closes #N` / `Resolves #N` — same convention as
# ``PRManager.find_label_drift``'s ``fixes_re``.
_FIXES_RE = re.compile(r"(?:fixes|closes|resolves)\s+#(\d+)", re.IGNORECASE)

# `agent/issue-1234` encodes its issue number in the branch name — the
# canonical namespace also parsed by
# ``WorkspaceGCLoop._parse_issue_from_branch``.
# #11281: BOTH mint patterns — manual dispatch (``agent/issue-{N}``)
# and Auto-Agent preflight (``agent/auto-agent-{N}``). Matching only
# the first made StaleIssueLoop treat live auto-agent branches as
# unrecognised, so their issues never got the truth comment and the
# branches were candidates for deletion while work was in flight.
_AGENT_BRANCH_RE = re.compile(r"^agent/(?:issue|auto-agent)-(\d+)$")


def extract_issue_number(branch: str, commit_messages: list[str]) -> int:
    """Determine which issue *branch* claims to fix.

    ``agent/issue-N`` branches encode the issue number in the branch name
    itself. Everything else (``fix/*`` and any other prefix) is resolved by
    scanning *commit_messages* (newest-first) for a GitHub closing-keyword
    reference. Returns ``0`` when neither yields a number — nothing to
    reconcile without an issue to comment on.
    """
    m = _AGENT_BRANCH_RE.match(branch)
    if m:
        return int(m.group(1))
    for message in commit_messages:
        fm = _FIXES_RE.search(message)
        if fm:
            return int(fm.group(1))
    return 0


BranchGCReason = Literal[
    "no_reference",
    "open_pr",
    "resolved",
    "young",
    "already_commented",
    "comment",
]


@dataclass(frozen=True)
class BranchGCDecision:
    """The comment/delete-eligibility verdict for one inventoried branch."""

    reason: BranchGCReason

    @property
    def should_comment(self) -> bool:
        """True exactly once — the tick the truth comment should be posted."""
        return self.reason == "comment"

    @property
    def eligible_for_delete_check(self) -> bool:
        """True when the branch is a genuine unmerged/no-open-PR candidate.

        Gates :func:`should_delete_branch`. Deliberately requires the truth
        comment to have ALREADY been posted on a prior tick (``reason ==
        "already_commented"``) — the spec posts the comment, THEN considers
        delete-or-escalate; a branch is never commented and deleted in the
        same cycle.
        """
        return self.reason == "already_commented"


def classify_branch(
    *,
    issue_number: int,
    age_days: int,
    has_open_pr: bool,
    issue_state: str,
    already_commented: bool,
    stale_days: int,
) -> BranchGCDecision:
    """Classify one inventoried branch per the GC decision matrix (#10011).

    Order matters — each check is a hard gate against a false alarm:

    1. No resolvable ``Fixes #N`` reference -> nothing to reconcile.
    2. An open PR exists for the branch -> still in flight, not a false claim.
    3. The referenced issue isn't ``OPEN`` (closed/unknown/lookup failure) ->
       either legitimately resolved already or a transient lookup miss;
       either way, never manufacture a false alarm from an unclear state.
    4. Younger than *stale_days* -> too early to call it stale.
    5. Already commented (dedup) -> comment phase is done; only the
       delete-or-escalate phase re-evaluates this branch going forward.
    6. Otherwise -> post the truth comment.
    """
    if issue_number <= 0:
        return BranchGCDecision("no_reference")
    if has_open_pr:
        return BranchGCDecision("open_pr")
    if issue_state != "OPEN":
        return BranchGCDecision("resolved")
    if age_days < stale_days:
        return BranchGCDecision("young")
    if already_commented:
        return BranchGCDecision("already_commented")
    return BranchGCDecision("comment")


def should_delete_branch(
    *, age_days: int, min_delete_age_days: int, delete_enabled: bool
) -> bool:
    """Gate the destructive delete step.

    Deletion defaults OFF (``delete_enabled=False`` is the operator's
    report-only default) and NEVER fires for a branch younger than
    *min_delete_age_days* even when enabled — branch deletion is
    destructive and the generous age floor is not overridable by the
    stale-comment threshold alone.
    """
    return delete_enabled and age_days >= min_delete_age_days


def build_truth_comment(branch: str, age_days: int) -> str:
    """Render the truth comment body posted on the referenced issue."""
    return (
        "## Unverified fix — branch never merged\n\n"
        f"Branch `{branch}` references this issue via a `Fixes #N`-style "
        f"commit but has sat unmerged for {age_days} days with no open PR "
        "against it. **Any prior comment on this issue claiming a fix was "
        "applied should be treated as unverified** until a PR from this "
        "branch (or a replacement) actually merges.\n\n"
        "*Filed by StaleIssueLoop's branch-GC reconciler (#10011) — the "
        "2026-07-19 groom found 9+ branches in this shape with false "
        "'fix applied' claims; #9553, #9554, and #9661 were nearly closed "
        "on that evidence.*"
    )


# ---------------------------------------------------------------------------
# Local unpushed-work detection (#10011 part 2)
# ---------------------------------------------------------------------------

_TRACK_AHEAD_RE = re.compile(r"ahead (\d+)")


@dataclass(frozen=True)
class UnpushedBranch:
    """One local branch with commits not yet pushed to its upstream."""

    branch: str
    upstream: str
    ahead: int


def parse_unpushed_branches(for_each_ref_output: str) -> list[UnpushedBranch]:
    """Parse ``git for-each-ref`` output into unpushed-work candidates.

    Expects lines produced by::

        git for-each-ref --format='%(refname:short)|%(upstream:short)|%(upstream:track)' refs/heads/

    A branch with no upstream (empty ``upstream`` field) has nothing to
    compare against and is skipped. ``[gone]`` (the upstream ref was
    deleted, typically after a merge) never carries an ``ahead`` count and
    is skipped too — this function only reports genuine "ahead of my own
    tracking branch" unpushed work, never a merged-and-cleaned-up branch.
    """
    results: list[UnpushedBranch] = []
    for line in for_each_ref_output.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        branch, upstream, track = (p.strip() for p in parts)
        if not branch or not upstream:
            continue
        match = _TRACK_AHEAD_RE.search(track)
        if not match:
            continue
        ahead = int(match.group(1))
        if ahead > 0:
            results.append(
                UnpushedBranch(branch=branch, upstream=upstream, ahead=ahead)
            )
    return results
