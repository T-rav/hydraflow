"""Stateful GitHub fake for scenario testing.

Tracks issues (labels, state, comments) and PRs (merged, CI status)
as in-memory state. Implements the async PRManager interface methods
that phases call via PipelineHarness.
"""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mockworld.fakes._factories import PRInfoFactory
from models import ClosedStageLabelDrift, LabelDrift, PRDiffStats
from pr_manager import PRManager

if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed

#: Mirrors ``HydraFlowConfig.dispatchable_stage_labels`` default (#10394): the
#: active pipeline-stage labels a CLOSED issue must never keep, or a label-scan
#: dispatcher would re-queue shipped work. This is the exact list, NOT a
#: ``startswith("hydraflow-")`` heuristic — terminal markers (``hydraflow-fixed``
#: / ``hydraflow-verify``) and orthogonal markers like ``hydraflow-auto-resolved``
#: are intentionally excluded so they survive a close.
_DISPATCHABLE_STAGE_LABELS = frozenset(
    {
        "hydraflow-find",
        "hydraflow-plan",
        "hydraflow-ready",
        "hydraflow-review",
        "hydraflow-hitl",
        "hydraflow-hitl-active",
        "hydraflow-hitl-autofix",
        "human-required",
        "hydraflow-in-progress",
    }
)


class RateLimitError(Exception):
    """Raised by FakeGitHub when rate-limit mode is exhausted.

    `secondary=True` represents GitHub's abuse-detection variant, which
    production code handles differently from primary rate limits.
    """

    def __init__(self, reset_in: int = 60, *, secondary: bool = False) -> None:
        self.reset_in = reset_in
        self.secondary = secondary
        suffix = " (secondary)" if secondary else ""
        super().__init__(f"FakeGitHub rate limit{suffix}; reset in {reset_in}s")


class FakeComment(str):
    """A single seeded/posted comment, structured but string-shaped.

    Subclasses ``str`` so every existing reader that treats
    ``FakeIssue.comments`` as ``list[str]`` (``in``, indexing, ``.lower()``,
    ``len()``) keeps working unmodified, while ``list_issue_comments`` (and
    any new reader) can pull the real per-comment ``login``/``created_at``
    off the same object instead of a hardcoded constant.
    """

    login: str
    created_at: str

    def __new__(
        cls,
        body: str,
        *,
        login: str = "fake-author",
        created_at: str = "2026-01-01T00:00:00Z",
    ) -> FakeComment:
        obj = super().__new__(cls, body)
        obj.login = login
        obj.created_at = created_at
        return obj

    @property
    def body(self) -> str:
        return str(self)


@dataclass
class FakeIssue:
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    state: str = "open"
    # Each entry is a FakeComment (str subclass carrying login/created_at).
    # list_issue_comments reads the structured fields directly; callers that
    # still treat this as list[str] (in/indexing/.lower()/len()) keep working
    # because FakeComment *is* a str.
    comments: list[FakeComment] = field(default_factory=list)
    updated_at: str = "2026-01-01T00:00:00Z"
    # Only meaningful once state == "closed"; mirrors gh's closedAt (#9727).
    # Empty = "not explicitly seeded": the closed listing falls back to
    # updated_at, mirroring GitHub (closing an issue touches both).
    closed_at: str = ""
    # Only meaningful once state == "closed"; mirrors gh's stateReason
    # ("COMPLETED" | "NOT_PLANNED"). Empty = closed without an explicit
    # reason — get_issue_state falls back to "COMPLETED", matching gh's
    # default close reason (#10025).
    state_reason: str = ""


# RC promotion naming (#10309). Matches config's ``rc_branch_prefix`` default —
# the fake serves one repo's worth of state under default naming. The fixed
# date mirrors FakeIssue's hard-coded timestamps: deterministic, no wall clock.
_RC_BRANCH_PREFIX = "rc/"
_RC_FIXED_DATE = "2026-01-01T00:00:00Z"


@dataclass
class FakePR:
    number: int
    issue_number: int
    branch: str
    merged: bool = False
    closed: bool = False
    ci_status: str = "pass"
    draft: bool = False
    url: str = ""
    mergeable: bool = True
    additions: int = 0
    deletions: int = 0
    base: str = "main"
    reviews: list[tuple[str, str]] = field(default_factory=list)
    checks: list[tuple[str, str]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    # PR author login (e.g. "dependabot[bot]"). Drives DependabotMergeLoop's
    # bot-PR eligibility (it matches pr.author against the configured bots).
    author: str = "fake-author"
    # GitHub's ``author.is_bot`` flag — true for GitHub Apps (Dependabot,
    # Renovate). DependabotMergeLoop's primary bot-detection signal, mirroring
    # the UI. Lets scenarios seed a bot PR without an author allowlist.
    is_bot: bool = False
    # Commit count used by ``find_label_drift`` (ADR-0088) to distinguish
    # zero-commit PRs from real ones. Defaults to 1 so seeded PRs look
    # "real" without explicit setup.
    commits: int = 1
    # The branch's _branch_tips sha at merge time (#11227), captured by
    # merge_pr/merge_promotion_pr before the tip is dropped — emulates
    # ``gh pr merge --delete-branch``. Empty when the branch was never
    # pushed/tracked at merge time.
    merged_head_sha: str = ""


class FakeGitHub:
    """Stateful fake for GitHub API (PRManager + IssueFetcher)."""

    _is_fake_adapter = True  # read by dashboard for MOCKWORLD banner

    def __init__(self) -> None:
        self._issues: dict[int, FakeIssue] = {}
        self._pr_diff_names: dict[int, list[str]] = {}
        # Per-PR seeded diff stats for get_pr_diff_stats (#10788 timeline).
        self._pr_diff_stats: dict[int, PRDiffStats] = {}
        # #9974: seeded workflow-run history for GateHealthLoop scenarios.
        self._workflow_runs: list[dict[str, Any]] = []
        self._workflow_jobs: dict[int, list[dict[str, Any]]] = {}
        self._workflow_artifacts: dict[int, int] = {}
        # #10027: run ids passed to rerun_workflow_failed, in call order.
        # Scenarios re-seed via add_workflow_run (status="in_progress") after
        # asserting a rerun fired, to simulate the mid-rerun stale-conclusion
        # trap the settled-red predicate must not double-fire on.
        self._workflow_reruns: list[int] = []
        self._prs: dict[int, FakePR] = {}
        self._pr_counter = 10_000
        # #10309: rc/* branches created via create_rc_branch, branch → ISO
        # committer date, so the promotion read side (find_open_promotion_pr /
        # list_rc_branches / list_recent_promotion_prs) is backed by real
        # state and StagingPromotionLoop can cut → find → monitor → merge its
        # own RC end-to-end against the fake (previously the reads were
        # hard-coded None/[] stubs).
        self._rc_branches: dict[str, str] = {}
        self._ci_scripts: dict[int, deque[tuple[bool, str]]] = {}
        self._comments: list[tuple[int, str]] = []
        self._ci_main_status: tuple[str, str] = ("success", "")
        self._rate_limit_remaining: int | None = None  # None = disabled
        self._rate_limit_reset_in: int = 60
        self._rate_limit_secondary: bool = False
        self._alerts: dict[str, list[Any]] = {}
        # Per-PR list of commit-diff strings for get_pr_recent_commit_diffs.
        # Each entry is a pre-rendered "## <sha> <title>\n<diff>" block.
        self._commit_diffs: dict[int, list[str]] = {}
        # Per-PR concatenated commit messages for get_pr_commit_messages —
        # the close-verification controller (#10358) reads these for the
        # Skip-Regression: opt-out trailer and Closes #N references.
        self._pr_commit_messages: dict[int, str] = {}
        # Per-PR full unified diff for get_pr_diff. Lets scenarios control the
        # diff a review sees (e.g. its blast radius for retry-budget tests).
        self._pr_diffs: dict[int, str] = {}
        # Catch-all diff for PRs without a per-PR seed. PR numbers come from an
        # opaque counter, so single-PR scenarios set this rather than guess.
        self._default_pr_diff: str | None = None
        # Per-PR CI failure log text for fetch_ci_failure_logs.
        self._ci_failure_logs: dict[int, str] = {}
        # Arch-staleness self-heal (DependabotMergeLoop). Per-PR count of
        # refresh_pr_branch_with_arch_regen calls, and per-PR override of the
        # bool it returns. When a PR is registered in _arch_refresh_outcome it
        # uses that value (and, when True, enqueues a fresh green CI result so
        # the next wait_for_ci tick sees the heal land); otherwise the call
        # defaults to True (a successful refresh) and enqueues green.
        self._arch_refresh_calls: dict[int, int] = {}
        self._arch_refresh_outcome: dict[int, bool] = {}
        # Mirrors PRManager._repo. Some loops (StaleIssueLoop) read this
        # attribute directly when constructing `gh` CLI args via _run_gh.
        # The value never reaches a real GitHub API in the sandbox.
        self._repo: str = "owner/repo"
        # Branch-protection rulesets keyed by name, served by fetch_rulesets
        # (ADR-0082, #9644). Mirrors the shape gh_fetch_rulesets returns:
        # {name: {name, target, enforcement, conditions, rules, ...}}.
        self._rulesets: dict[str, dict[str, Any]] = {}
        # Classic branch-protection config keyed by branch name, served by
        # fetch_legacy_protection (#10148). Mirrors the shape GitHub's
        # ``/repos/{repo}/branches/{branch}/protection`` returns. Default
        # empty: fetch_legacy_protection returns None (no classic rule) for
        # every branch, matching the raw ``gh api`` 404 case, so existing
        # ruleset-only seeds see no new drift from this seam.
        self._legacy_protection: dict[str, dict[str, Any]] = {}
        # #11227: branch -> head sha, the fake's single source of truth for
        # ref existence. push_branch/create_rc_branch/push_synthetic_commit/
        # ensure_branch_exists/create_pr are the only writers; delete_branch
        # and merge_pr/merge_promotion_pr (delete-branch-on-merge) are the
        # only removers. _run_gh's matching-refs read is served straight off
        # this map's keys.
        self._branch_tips: dict[str, str] = {}
        # branch -> (last_commit_iso, [messages newest-first]), backing the
        # _run_gh commits read StaleIssueLoop's branch-GC composes for a
        # branch's age and its ``Fixes #N`` reference.
        self._branch_commits: dict[str, tuple[str, list[str]]] = {}
        # Per-branch force-push counter — the only way an ordinary re-push
        # (force=False) leaves the tip sha unchanged is if force-pushes are
        # the sole source of a *new* sha; this counter is that source.
        self._branch_force_push_counts: dict[str, int] = {}

    @classmethod
    def from_seed(cls, seed: MockWorldSeed) -> FakeGitHub:
        """Construct a FakeGitHub populated from a MockWorldSeed."""
        gh = cls()
        for issue_dict in seed.issues:
            gh.add_issue(
                number=issue_dict["number"],
                title=issue_dict["title"],
                body=issue_dict["body"],
                labels=list(issue_dict.get("labels", [])),
                state=issue_dict.get("state", "open"),
                updated_at=issue_dict.get("updated_at"),
            )
        for issue_number, comment_dicts in seed.comments.items():
            for comment_dict in comment_dicts:
                gh.add_seeded_comment(
                    issue_number,
                    comment_dict.get("body", ""),
                    login=comment_dict.get("login", "fake-author"),
                    created_at=comment_dict.get("created_at", "2026-01-01T00:00:00Z"),
                )
        for pr_dict in seed.prs:
            gh.add_pr(
                number=pr_dict["number"],
                issue_number=pr_dict["issue_number"],
                branch=pr_dict["branch"],
                ci_status=pr_dict.get("ci_status", "pass"),
                merged=pr_dict.get("merged", False),
                author=pr_dict.get("author", "fake-author"),
                is_bot=pr_dict.get("is_bot", False),
                mergeable=pr_dict.get("mergeable", True),
            )
            for label in pr_dict.get("labels", []):
                gh.add_pr_label(pr_dict["number"], label)
        # Apply main-branch CI status if the seed overrides the default green.
        conclusion, url = seed.main_branch_ci_status
        if conclusion != "success":
            gh.set_ci_main_status(conclusion, url)
        for name, cfg in seed.rulesets.items():
            gh.add_ruleset(name, cfg)
        for branch_dict in seed.branches:
            gh.seed_branch(
                branch_dict["branch"],
                sha=branch_dict.get("sha"),
                last_commit_at=branch_dict.get("last_commit_at", _RC_FIXED_DATE),
                commit_messages=branch_dict.get("commit_messages"),
            )
        return gh

    # --- Seed API ---

    def add_issue(
        self,
        number: int,
        title: str,
        body: str,
        labels: list[str] | None = None,
        state: str = "open",
        updated_at: str | None = None,
    ) -> None:
        """Seed an issue. ``state`` accepts ``"open"`` (default) or ``"closed"``.

        A closed seed issue reports ``COMPLETED`` from ``get_issue_state``
        (close-reason defaulting mirrors gh, #10025) — the surface loops like
        workspace_gc/epic_sweeper consult before acting (#9543).

        ``updated_at`` (#9544) lets a scenario control the issue's staleness
        independently of ``FakeIssue``'s hard-coded ``2026-01-01T00:00:00Z``
        default — needed to drive time-triggered loops like
        ``stale_issue_gc`` down BOTH branches (closes a genuinely stale
        issue, skips a genuinely fresh one) instead of every seeded issue
        reading as equally stale. ``None`` (default) leaves ``FakeIssue``'s
        own default untouched — back-compat for every pre-#9544 seed.
        """
        issue = FakeIssue(
            number=number,
            title=title,
            body=body,
            labels=labels or [],
            state=state,
        )
        if updated_at:
            issue.updated_at = updated_at
        self._issues[number] = issue

    def add_seeded_comment(
        self,
        issue_number: int,
        body: str,
        *,
        login: str = "fake-author",
        created_at: str = "2026-01-01T00:00:00Z",
    ) -> None:
        """Seed-API helper: attach a structured comment to a fake issue.

        Unlike ``post_comment`` (the runtime path bots/routes call), this
        lets a scenario control the comment's author and timestamp — needed
        for e.g. human-steering directive sequences that rely on a real
        ``created_at`` high-water-mark across distinct authors.
        """
        if issue_number not in self._issues:
            raise KeyError(f"FakeGitHub: no issue {issue_number}")
        self._issues[issue_number].comments.append(
            FakeComment(body, login=login, created_at=created_at)
        )

    def add_pr(
        self,
        *,
        number: int,
        issue_number: int,
        branch: str,
        ci_status: str = "pass",
        merged: bool = False,
        author: str = "fake-author",
        is_bot: bool = False,
        mergeable: bool = True,
    ) -> None:
        """Directly insert a PR record (sync helper for test seeding).

        The async ``create_pr`` handles the production path; this helper
        exists so scenario seeds can set up a fully-populated world
        synchronously. ``mergeable=False`` seeds a CONFLICTING PR that
        ``list_conflicting_prs`` surfaces to merge_state_watcher (#9543).
        """
        self._prs[number] = FakePR(
            number=number,
            issue_number=issue_number,
            branch=branch,
            merged=merged,
            ci_status=ci_status,
            author=author,
            is_bot=is_bot,
            mergeable=mergeable,
        )

    def add_pr_label(self, pr_number: int, label: str) -> None:
        """Seed-API helper: attach a label to a fake PR."""
        if pr_number not in self._prs:
            raise KeyError(f"FakeGitHub: no PR {pr_number}")
        pr = self._prs[pr_number]
        if label not in pr.labels:
            pr.labels.append(label)

    def add_alerts(self, *, branch: str, alerts: list[Any]) -> None:
        """Script code-scanning alerts returned by fetch_code_scanning_alerts."""
        self._alerts[branch] = list(alerts)

    def add_ruleset(self, name: str, config: dict[str, Any]) -> None:
        """Seed-API helper: register a live branch-protection ruleset by name.

        The stored config is what ``fetch_rulesets`` serves — shaped like
        GitHub's ``/repos/{repo}/rulesets/{id}`` response so it can be diffed
        against the canonical contract by ``branch_protection_audit`` (#9644).
        Stored as a shallow copy so later mutation of the caller's dict does
        not retroactively alter seeded state.
        """
        self._rulesets[name] = dict(config)

    def add_legacy_protection(self, branch: str, config: dict[str, Any]) -> None:
        """Seed-API helper: register classic branch-protection config for a branch.

        The stored config is what ``fetch_legacy_protection`` serves — shaped
        like GitHub's ``/repos/{repo}/branches/{branch}/protection`` response
        (``{"required_status_checks": {"contexts": [...], "checks": [...]}}``)
        so ``branch_protection_audit.undeclared_legacy_contexts`` can detect an
        undeclared legacy layer stacking extra required checks on top of the
        ruleset (#10148). Stored as a shallow copy so later mutation of the
        caller's dict does not retroactively alter seeded state.
        """
        self._legacy_protection[branch] = dict(config)

    def seed_branch(
        self,
        branch: str,
        *,
        sha: str | None = None,
        last_commit_at: str = "2026-01-01T00:00:00Z",
        commit_messages: list[str] | None = None,
    ) -> None:
        """Seed-API helper: register a branch ref with a tip sha + commit history.

        Mirrors what ``push_branch`` records so a scenario can seed a branch
        without driving the full push flow. ``sha`` defaults to the same
        deterministic ``sha-<branch>`` convention ``push_branch`` uses.
        ``commit_messages`` (newest-first) backs the ``_run_gh`` commits read
        ``StaleIssueLoop``'s branch-GC reconciler composes for branch age and
        ``Fixes #N`` extraction; defaults to one generic commit so a bare
        ``seed_branch(branch)`` still yields a non-empty commits read.
        """
        self._branch_tips[branch] = sha or f"sha-{branch}"
        self._branch_commits[branch] = (
            last_commit_at,
            list(commit_messages) if commit_messages else ["auto-agent commit"],
        )

    def branch_tip(self, branch: str) -> str | None:
        """Return the current tip sha for *branch*, or None if untracked."""
        return self._branch_tips.get(branch)

    def branch_tips(self) -> dict[str, str]:
        """Return a defensive copy of every tracked branch -> tip sha."""
        return dict(self._branch_tips)

    def script_ci(self, pr_number: int, results: list[tuple[bool, str]]) -> None:
        self._ci_scripts[pr_number] = deque(results)

    def script_arch_refresh(self, pr_number: int, *, succeeds: bool = True) -> None:
        """Script the outcome of ``refresh_pr_branch_with_arch_regen`` for a PR.

        ``succeeds=True`` (default): the next refresh returns True and enqueues a
        fresh ``(True, "All checks passed")`` CI result so the following
        ``wait_for_ci`` tick sees the heal land green (the stale-arch happy
        path). ``succeeds=False``: the refresh returns False without changing CI
        (e.g. a real non-generated conflict), so the caller falls through to its
        failure strategy.
        """
        self._arch_refresh_outcome[pr_number] = succeeds

    def arch_refresh_call_count(self, pr_number: int) -> int:
        """Return how many times the loop arch-refreshed *pr_number*."""
        return self._arch_refresh_calls.get(pr_number, 0)

    def set_ci_main_status(self, conclusion: str, url: str = "") -> None:
        """Script the response for get_latest_ci_status (main branch CI)."""
        self._ci_main_status = (conclusion, url)

    def seed_pr_commit_diffs(self, pr_number: int, diffs: list[str]) -> None:
        """Seed pre-rendered commit-diff blocks for *pr_number*.

        Each entry should be a ``## <sha> <title>\\n<diff>`` string.
        ``get_pr_recent_commit_diffs`` returns the last *n* of these.
        """
        self._commit_diffs[pr_number] = list(diffs)

    def seed_pr_diff(self, pr_number: int, diff: str) -> None:
        """Seed the full unified diff ``get_pr_diff`` returns for *pr_number*.

        Lets a scenario control the diff a review sees — e.g. its blast radius
        (critical paths / src line count), which drives the PostVerifyAdvisor
        retry budget. Absent a seed, ``get_pr_diff`` returns the default stub.
        """
        self._pr_diffs[pr_number] = diff

    def set_default_pr_diff(self, diff: str) -> None:
        """Set the diff ``get_pr_diff`` returns for any PR lacking a per-PR seed.

        Convenience for single-PR scenarios that want to control blast radius
        without knowing the opaque PR number assigned by ``create_pr``.
        """
        self._default_pr_diff = diff

    def set_issue_updated_at(self, issue_number: int, updated_at: str) -> None:
        """Set the updated_at timestamp on a seeded issue."""
        if issue_number in self._issues:
            self._issues[issue_number].updated_at = updated_at

    def set_issue_closed_at(self, issue_number: int, closed_at: str) -> None:
        """Set the closed_at timestamp on a seeded issue (#9727)."""
        if issue_number in self._issues:
            self._issues[issue_number].closed_at = closed_at

    def set_rate_limit_mode(
        self,
        *,
        remaining: int = 0,
        reset_in: int = 60,
        secondary: bool = False,
    ) -> None:
        """Enable rate-limit gating; next *remaining* calls succeed, then raise."""
        self._rate_limit_remaining = remaining
        self._rate_limit_reset_in = reset_in
        self._rate_limit_secondary = secondary

    def clear_rate_limit(self) -> None:
        self._rate_limit_remaining = None
        self._rate_limit_secondary = False

    def _maybe_rate_limit(self) -> None:
        if self._rate_limit_remaining is None:
            return
        if self._rate_limit_remaining <= 0:
            raise RateLimitError(
                reset_in=self._rate_limit_reset_in,
                secondary=self._rate_limit_secondary,
            )
        self._rate_limit_remaining -= 1

    # --- Query API ---

    def issue(self, number: int) -> FakeIssue:
        if number not in self._issues:
            msg = f"FakeGitHub: no issue {number}"
            raise KeyError(msg)
        return self._issues[number]

    def pr(self, number: int) -> FakePR:
        if number not in self._prs:
            msg = f"FakeGitHub: no PR {number}"
            raise KeyError(msg)
        return self._prs[number]

    def pr_for_issue(self, issue_number: int) -> FakePR | None:
        for p in self._prs.values():
            if p.issue_number == issue_number:
                return p
        return None

    # --- PRManager interface (async methods called by phases) ---

    async def transition(
        self,
        issue_number: int,
        new_stage: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        self._maybe_rate_limit()
        _ = pr_number
        stage_label_map = {
            "find": "hydraflow-find",
            "triage": "hydraflow-triage",
            "plan": "hydraflow-plan",
            "ready": "hydraflow-ready",
            "review": "hydraflow-review",
            "done": "hydraflow-done",
            "hitl": "hydraflow-hitl",
            # Mirrors PRManager.transition._STAGE_LABEL. Without this, a
            # "diagnose" transition (review-fix-cap escalation) labels the
            # issue bare "diagnose"; the DiagnosticLoop scans for
            # "hydraflow-diagnose" and never sees it, so HITL never forms (s05).
            "diagnose": "hydraflow-diagnose",
        }
        new_label = stage_label_map.get(new_stage, new_stage)
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [
                lbl for lbl in issue.labels if not lbl.startswith("hydraflow-")
            ]
            issue.labels.append(new_label)

    async def swap_pipeline_labels(
        self,
        issue_number: int,
        new_label: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        self._maybe_rate_limit()
        _ = pr_number
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [
                lbl for lbl in issue.labels if not lbl.startswith("hydraflow-")
            ]
            issue.labels.append(new_label)

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            for label in labels:
                if label not in self._issues[issue_number].labels:
                    self._issues[issue_number].labels.append(label)

    async def remove_label(self, issue_number: int, label: str) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.labels = [lbl for lbl in issue.labels if lbl != label]

    async def post_comment(self, issue_number: int, body: str) -> None:
        self._maybe_rate_limit()
        self._comments.append((issue_number, body))
        if issue_number in self._issues:
            self._issues[issue_number].comments.append(FakeComment(body))

    async def post_pr_comment(self, pr_number: int, body: str) -> None:
        self._maybe_rate_limit()
        self._comments.append((pr_number, body))

    async def submit_review(
        self, pr_number: int, verdict: Any, body: str, **_kw: Any
    ) -> bool:
        """Submit a formal PR review (no-op stub — always returns True)."""
        self._maybe_rate_limit()
        return True

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        self._maybe_rate_limit()
        num = max(self._issues.keys(), default=9000) + 1
        self.add_issue(num, title, body, labels=labels)
        return num

    async def close_task(self, issue_number: int) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            self._issues[issue_number].state = "closed"

    async def close_issue(
        self, issue_number: int, *, reason: str | None = None
    ) -> bool:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.state = "closed"
            # Mirror gh: `--reason "not planned"` -> stateReason NOT_PLANNED;
            # no --reason -> COMPLETED (get_issue_state's empty fallback).
            issue.state_reason = reason.upper().replace(" ", "_") if reason else ""
            # Mirror PRManager.close_issue's #10394 strip: a closed issue must
            # never keep an active pipeline-stage label, or a label-scan
            # dispatcher would re-queue shipped work. Scoped to the exact
            # dispatchable set (terminal + orthogonal markers survive).
            issue.labels = [
                lbl for lbl in issue.labels if lbl not in _DISPATCHABLE_STAGE_LABELS
            ]
        elif issue_number in self._prs:
            # gh treats PRs as issues — `gh issue close <pr#>` closes the PR.
            # StagingPromotionLoop closes red promotion PRs through this exact
            # call (#10309); without the fallthrough the fake left them open
            # and the loop re-found the same "open" PR every tick.
            self._prs[issue_number].closed = True
        return True

    async def reopen_issue(self, issue_number: int) -> bool:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.state = "open"
            issue.state_reason = ""
            issue.closed_at = ""
        return True

    async def close_pr(self, pr_number: int) -> bool:
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is not None:
            pr.closed = True
        return True

    async def find_existing_issue(self, title: str) -> int:
        self._maybe_rate_limit()
        for issue in self._issues.values():
            if issue.title == title and issue.state == "open":
                return issue.number
        return 0

    async def push_branch(
        self,
        worktree_path: Any = None,
        branch: str = "",
        *,
        force: bool = False,
        **_kwargs: Any,
    ) -> bool:
        self._maybe_rate_limit()
        _ = worktree_path
        if branch:
            if force:
                n = self._branch_force_push_counts.get(branch, 0) + 1
                self._branch_force_push_counts[branch] = n
                self._branch_tips[branch] = f"sha-{branch}-force-{n}"
            else:
                self._branch_tips.setdefault(branch, f"sha-{branch}")
        return True

    async def create_pr(
        self,
        issue: Any,
        branch: str,
        *,
        draft: bool = False,
        **_unused: Any,
    ) -> Any:
        self._maybe_rate_limit()
        number = self._pr_counter
        self._pr_counter += 1
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        self._prs[number] = FakePR(
            number=number,
            issue_number=issue_number,
            branch=branch,
            draft=draft,
            url=f"https://github.com/test/repo/pull/{number}",
        )
        # Opening a PR implies the branch already exists on the remote — do
        # not clobber a tip push_branch already recorded (#11227).
        self._branch_tips.setdefault(branch, f"sha-{branch}")
        return PRInfoFactory.create(
            number=number,
            issue_number=issue_number,
            branch=branch,
            draft=draft,
        )

    async def find_open_pr_for_branch(
        self,
        branch: str,
        *,
        issue_number: int | None = None,
        **_unused: Any,
    ) -> Any:
        self._maybe_rate_limit()
        for p in self._prs.values():
            if p.branch == branch and not p.merged and not p.closed:
                return PRInfoFactory.create(
                    number=p.number,
                    issue_number=p.issue_number,
                    branch=p.branch,
                )
        # No open PR for this branch — signal absence with number=0
        return PRInfoFactory.create(
            number=0,
            issue_number=issue_number or 0,
            branch=branch,
        )

    async def branch_has_diff_from_main(self, branch: str) -> bool:
        self._maybe_rate_limit()
        return True

    async def add_pr_labels(self, pr_number: int, labels: list[str]) -> None:
        """Mirror PRManager.add_pr_labels — append each label idempotently."""
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return
        for label in labels:
            if label not in pr.labels:
                pr.labels.append(label)

    async def remove_pr_label(self, pr_number: int, label: str) -> None:
        """Mirror PRManager.remove_pr_label — drop *label* if present."""
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return
        if label in pr.labels:
            pr.labels.remove(label)

    async def get_pr_labels(self, pr_number: int) -> list[str]:
        """Return the label names on a PR (empty list when unknown)."""
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return []
        return list(pr.labels)

    async def get_pr_diff(self, pr_number: int) -> str:
        self._maybe_rate_limit()
        if pr_number in self._pr_diffs:
            return self._pr_diffs[pr_number]
        if self._default_pr_diff is not None:
            return self._default_pr_diff
        return "diff --git a/x b/x"

    async def get_pr_head_sha(self, pr_number: int) -> str:
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is not None:
            tip = self._branch_tips.get(pr.branch)
            if tip:
                return tip
        return "abc123"

    def set_pr_diff_stats(self, pr_number: int, stats: PRDiffStats) -> None:
        """Seed the diff stats one PR reports (#10788 timeline scenarios)."""
        self._pr_diff_stats[pr_number] = stats.copy()

    async def get_pr_diff_stats(self, pr_number: int) -> PRDiffStats:
        """Return seeded diff stats, or a deterministic non-empty default.

        Mirrors :meth:`PRManager.get_pr_diff_stats` (#10788): a snake_case
        ``PRDiffStats`` the operator timeline can render. Defaults to a small
        single-file diff so unseeded scenarios still exercise the enriched
        path rather than the degraded (keys-absent) one.
        """
        self._maybe_rate_limit()
        seeded = self._pr_diff_stats.get(pr_number)
        if seeded is not None:
            return seeded.copy()
        return PRDiffStats(
            commit_sha="abc123", files_changed=1, additions=1, deletions=0
        )

    def set_pr_diff_names(self, pr_number: int, names: list[str]) -> None:
        """Seed the changed-file list one PR reports (#9974 blame scenarios)."""
        self._pr_diff_names[pr_number] = list(names)

    async def get_pr_diff_names(self, pr_number: int) -> list[str]:
        self._maybe_rate_limit()
        return list(self._pr_diff_names.get(pr_number, ["src/app.py"]))

    def set_pr_commit_messages(self, pr_number: int, message: str) -> None:
        """Seed the concatenated commit messages get_pr_commit_messages returns.

        Carries the Skip-Regression: trailer and Closes #N references the
        close-verification controller (#10358) reads.
        """
        self._pr_commit_messages[pr_number] = message

    async def get_pr_commit_messages(self, pr_number: int) -> str:
        self._maybe_rate_limit()
        return self._pr_commit_messages.get(pr_number, "")

    async def get_pr_recent_commit_diffs(self, pr_number: int, *, n: int = 3) -> str:
        """Return a stub diff block for the last *n* commits on *pr_number*.

        Returns a deterministic non-empty string so scenarios can assert that
        the context block is populated without hitting the GitHub API.
        """
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        branch = pr.branch if pr is not None else f"pr-{pr_number}"
        commits = self._commit_diffs.get(pr_number) or []
        if commits:
            return "\n\n".join(commits[-n:])
        return f"## deadbeef stub-commit — {branch}\ndiff --git a/x b/x\n+fix"

    async def get_pr_approvers(self, pr_number: int) -> list[str]:
        self._maybe_rate_limit()
        return ["octocat"]

    async def get_pr_checks(self, pr_number: int) -> list[dict[str, str]]:
        """Serve seeded ``FakePR.checks`` (#10260). Defaults to empty — same
        falsy-empty contract as before, so epic detail rendering
        (EpicManager._enrich_pr_status) derives no CI status rather than
        AttributeError-ing when a scenario hasn't seeded checks."""
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return []
        return [{"name": name, "state": state} for name, state in pr.checks]

    async def find_open_resolving_pr(self, issue_number: int) -> int | None:
        """In-memory mirror of :meth:`PRPort.find_open_resolving_pr` (#10260).

        Unlike the real adapter (which parses ``Fixes #N`` from the PR
        body), the fake's ``FakePR.issue_number`` already encodes the link.
        Draft PRs are excluded, mirroring the real adapter.
        """
        self._maybe_rate_limit()
        for pr in self._prs.values():
            if (
                pr.issue_number == issue_number
                and not pr.merged
                and not pr.closed
                and not pr.draft
            ):
                return pr.number
        return None

    async def get_pr_reviews(self, pr_number: int) -> list[dict[str, str]]:
        """No GitHub reviews in the air-gapped sandbox. Empty → epic detail
        rendering derives no review status rather than AttributeError-ing (same
        /api/epics rendering path as get_pr_checks)."""
        self._maybe_rate_limit()
        return []

    async def fetch_code_scanning_alerts(self, branch: str, **_kw: Any) -> list:
        self._maybe_rate_limit()
        return list(self._alerts.get(branch, []))

    async def wait_for_ci(
        self, pr_number: int, *_args: Any, **_kw: Any
    ) -> tuple[bool, str]:
        self._maybe_rate_limit()
        q = self._ci_scripts.get(pr_number)
        if q:
            return q.popleft()
        return (True, "CI passed")

    async def fetch_ci_failure_logs(self, pr_number: int, **_kw: Any) -> str:
        self._maybe_rate_limit()
        return self._ci_failure_logs.get(pr_number, "")

    def seed_ci_failure_log(self, pr_number: int, log: str) -> None:
        """Seed the CI failure log text returned by fetch_ci_failure_logs."""
        self._ci_failure_logs[pr_number] = log

    async def merge_pr(self, pr_number: int, **_kw: Any) -> bool:
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is not None:
            pr.merged = True
            self._drop_branch_ref_on_merge(pr)
        return True

    def _drop_branch_ref_on_merge(self, pr: FakePR) -> None:
        """Emulate ``gh pr merge --delete-branch``: stamp the merge-time tip
        sha on *pr* then drop the ref (#11227). No-ops (records no sha) when
        the branch was never pushed/tracked."""
        pr.merged_head_sha = self._branch_tips.pop(pr.branch, "")
        self._branch_commits.pop(pr.branch, None)
        self._rc_branches.pop(pr.branch, None)

    async def refresh_pr_branch_with_arch_regen(
        self, pr_number: int, branch: str, **_kw: Any
    ) -> bool:
        """Fake of the arch-staleness self-heal.

        Records the call. Returns the scripted outcome (default True). On a
        successful refresh, enqueues a fresh green CI result so the next
        ``wait_for_ci`` tick sees the heal land — mirroring production, where
        the merge+regen+push re-triggers CI which then passes.
        """
        self._maybe_rate_limit()
        self._arch_refresh_calls[pr_number] = (
            self._arch_refresh_calls.get(pr_number, 0) + 1
        )
        succeeds = self._arch_refresh_outcome.get(pr_number, True)
        if succeeds:
            self._ci_scripts.setdefault(pr_number, deque()).append(
                (True, "All checks passed")
            )
        return succeeds

    # --- Loop-required PRPort methods ---

    @staticmethod
    def _issue_summary(issue: FakeIssue) -> dict[str, Any]:
        """GitHubIssueSummary-style projection of one issue.

        Shared by ``list_issues_by_label`` / ``list_open_issues`` — previously
        two byte-identical copies (#10025). ``labels`` mirrors the gh wire
        shape (``{"name": ...}``, #9943) so filters reading ``lbl["name"]``
        behave identically under the fake and the adapter.
        """
        return {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "updated_at": getattr(issue, "updated_at", "2026-01-01T00:00:00Z"),
            "labels": [{"name": name} for name in issue.labels],
        }

    async def list_issues_by_label(self, label: str) -> list[dict[str, Any]]:
        """Return open issues carrying *label* as GitHubIssueSummary-style dicts."""
        self._maybe_rate_limit()
        return [
            self._issue_summary(issue)
            for issue in self._issues.values()
            if issue.state == "open" and label in issue.labels
        ]

    async def list_open_issues(self) -> list[dict[str, Any]]:
        """Return ALL open issues (no label filter), mirroring the gh projection.

        Used by IssueRefinementLoop's backlog-wide sweep (#9957).
        """
        self._maybe_rate_limit()
        return [
            self._issue_summary(issue)
            for issue in self._issues.values()
            if issue.state == "open"
        ]

    async def list_open_issue_numbers(self, limit: int = 500) -> list[int]:
        """Return numbers of ALL open issues, mirroring the gh projection (#9905)."""
        self._maybe_rate_limit()
        numbers = [
            issue.number for issue in self._issues.values() if issue.state == "open"
        ]
        return sorted(numbers)[:limit]

    def add_workflow_run(
        self,
        run_id: int,
        *,
        workflow: str,
        workflow_file: str = "",
        conclusion: str,
        created_at: str = "2026-07-01T00:00:00Z",
        pr_number: int = 0,
        jobs: list[dict[str, Any]] | None = None,
        artifact_count: int = 0,
        url: str = "",
        status: str = "completed",
        run_started_at: str = "",
        updated_at: str = "",
    ) -> None:
        """Seed one workflow run (+jobs/artifacts) for gate-health scenarios.

        ``workflow`` is the run's **display name** (the workflow's ``.name``,
        e.g. ``"CI"``) — what live GitHub returns in run listings and what
        :meth:`list_workflow_runs` projects. ``workflow_file`` is the workflow
        **file name** (e.g. ``"ci.yml"``) — the identifier the real
        ``PRManager.list_runs_for_workflow`` puts in the REST path, and the key
        :meth:`list_runs_for_workflow` matches on here. They differ on live
        GitHub, so seeding a file name in ``workflow`` would pass in MockWorld
        yet mislead any consumer that correlates blame by display name (#10899,
        #10911). ``workflow_file`` defaults to ``workflow`` for callers that key
        by only one identifier.

        ``url``/``status``/``run_started_at``/``updated_at`` (#9814) feed
        :meth:`list_runs_for_workflow`; the timestamps default to
        ``created_at`` — mirroring the adapter's ``run_started_at``
        fallback — so duration-math consumers see 0s, never a crash.
        """
        self._workflow_runs.append(
            {
                "id": run_id,
                "workflow": workflow,
                "workflow_file": workflow_file or workflow,
                "conclusion": conclusion,
                "created_at": created_at,
                "pr_number": pr_number,
                "url": url,
                "status": status,
                "run_started_at": run_started_at or created_at,
                "updated_at": updated_at or created_at,
            }
        )
        self._workflow_jobs[run_id] = jobs or []
        self._workflow_artifacts[run_id] = artifact_count

    async def list_workflow_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest-first slice of the seeded run history (#9974).

        Projects exactly the repo-wide blame-correlation shape — the
        #9814 seed extras stay out so pre-existing consumers see the
        same rows as before.
        """
        self._maybe_rate_limit()
        newest_first = sorted(
            self._workflow_runs, key=lambda r: str(r["created_at"]), reverse=True
        )
        return [
            {
                "id": r["id"],
                "workflow": r["workflow"],
                "conclusion": r["conclusion"],
                "created_at": r["created_at"],
                "pr_number": r["pr_number"],
            }
            for r in newest_first[:limit]
        ]

    async def list_runs_for_workflow(
        self, workflow: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Newest-first runs of ONE workflow file in the port shape (#9814).

        Keyed on the seeded ``workflow_file`` (the file name, e.g. ``ci.yml``),
        mirroring the real adapter which passes the file name in the REST path
        ``actions/workflows/{workflow}/runs`` — NOT the display name that
        :meth:`list_workflow_runs` returns (#10899).
        """
        self._maybe_rate_limit()
        matching = sorted(
            (r for r in self._workflow_runs if r["workflow_file"] == workflow),
            key=lambda r: str(r["created_at"]),
            reverse=True,
        )
        return [
            {
                "id": r["id"],
                "url": r["url"],
                "status": r["status"],
                "conclusion": r["conclusion"],
                "created_at": r["created_at"],
                "run_started_at": r["run_started_at"],
                "updated_at": r["updated_at"],
            }
            for r in matching[:limit]
        ]

    async def get_workflow_run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        self._maybe_rate_limit()
        return [dict(j) for j in self._workflow_jobs.get(run_id, [])]

    async def count_workflow_run_artifacts(self, run_id: int) -> int:
        self._maybe_rate_limit()
        return self._workflow_artifacts.get(run_id, 0)

    async def rerun_workflow_failed(self, run_id: int) -> bool:
        """Record a rerun trigger for *run_id* (#10027).

        Mirrors ``PRManager.rerun_workflow_failed``'s always-True success
        path; does not itself mutate the seeded run/job state — scenarios
        that want to simulate a rerun's effect re-seed via
        :meth:`add_workflow_run`.
        """
        self._maybe_rate_limit()
        self._workflow_reruns.append(run_id)
        return True

    async def list_closed_issues_by_label(
        self,
        label: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return closed issues carrying *label* (most recent up to *limit*).

        ``closed_at`` mirrors the adapter's ``closedAt`` projection (#9727)
        so churn windows keyed on close time behave identically under the
        fake and the real port. ``labels`` (#8996) reuses ``_issue_summary``
        so ``escalation_reconcile.is_bot_close`` sees the same gh-wire-shape
        label list under the fake as under the real adapter.
        """
        self._maybe_rate_limit()
        rows = [
            {
                **self._issue_summary(issue),
                "closed_at": getattr(issue, "closed_at", "")
                or getattr(issue, "updated_at", "2026-01-01T00:00:00Z"),
            }
            for issue in self._issues.values()
            if issue.state != "open" and label in issue.labels
        ]
        return rows[:limit]

    async def list_prs_by_label(self, label: str) -> list[Any]:
        """Return open (non-merged) PRs carrying *label*.

        Mirrors ``PRManager.list_prs_by_label`` (which delegates to
        ``gh pr list --label <label> --state open``). Used by
        SandboxFailureFixerLoop to poll auto-fix candidates.

        The returned ``PRInfo`` carries the full label set so secondary
        filters (e.g. the ``no-auto-fix`` opt-out) can be applied without
        a second round-trip.
        """
        self._maybe_rate_limit()
        out: list[Any] = []
        for pr in self._prs.values():
            if pr.merged:
                continue
            if label not in pr.labels:
                continue
            out.append(
                PRInfoFactory.create(
                    number=pr.number,
                    issue_number=pr.issue_number,
                    branch=pr.branch,
                    draft=pr.draft,
                    labels=list(pr.labels),
                )
            )
        return out

    async def find_label_drift(self) -> list[LabelDrift]:
        """In-memory mirror of :meth:`PRPort.find_label_drift` (ADR-0088).

        Walks open, non-merged PRs and pairs each with its linked issue;
        classifies drift kinds the same way ``PRManager.find_label_drift``
        classifies them.
        """
        self._maybe_rate_limit()
        pre_pr_labels = {"hydraflow-ready", "hydraflow-plan", "hydraflow-find"}
        post_pr_labels = {"hydraflow-fixed", "hydraflow-hitl"}
        out: list[LabelDrift] = []
        for pr in self._prs.values():
            if pr.merged:
                continue
            issue = self._issues.get(pr.issue_number)
            if issue is None:
                continue
            # Mirror PRManager.find_label_drift: the in-progress claim marker
            # (#10168) is not a pipeline stage, so exclude it from the stage
            # pick — a ready+in-progress issue must read as ``hydraflow-ready``.
            pr_pipeline = next(
                (
                    lbl
                    for lbl in pr.labels
                    if lbl.startswith("hydraflow-") and lbl != "hydraflow-in-progress"
                ),
                "",
            )
            issue_pipeline = next(
                (
                    lbl
                    for lbl in issue.labels
                    if lbl.startswith("hydraflow-") and lbl != "hydraflow-in-progress"
                ),
                "",
            )
            commits = pr.commits

            # More specific — checked first (#10260): a resolved-but-stale
            # escalation label outranks the pipeline-stage drift kinds below.
            # Requires BOTH labels — see the matching comment in
            # PRManager.find_label_drift for why bare `hitl-escalation`
            # (filed by loops other than diagnostic_loop, with no pipeline
            # label backing it) must not be cleared this way. Draft PRs are
            # excluded — mirrors find_open_resolving_pr's draft check.
            escalations = set(issue.labels) & {"hitl-escalation", "diagnose-failed"}
            kind: str | None = None
            issue_label = issue_pipeline
            if (
                {"hitl-escalation", "diagnose-failed"} <= set(issue.labels)
                and not pr.draft
                and pr.checks
                and all(
                    state.upper() in {"SUCCESS", "NEUTRAL", "SKIPPED"}
                    for _name, state in pr.checks
                )
            ):
                kind = "escalated_with_resolving_pr"
                issue_label = ",".join(sorted(escalations))

            if kind is None:
                if (
                    issue_pipeline in pre_pr_labels
                    and pr_pipeline == "hydraflow-review"
                    and commits > 0
                ):
                    kind = "pr_ahead_of_issue"
                elif pr_pipeline in pre_pr_labels and commits > 0:
                    kind = "pr_at_pre_pr_stage"
                elif pr_pipeline in post_pr_labels and issue_pipeline in pre_pr_labels:
                    kind = "pr_ahead_of_issue"

            if kind is None:
                continue
            out.append(
                LabelDrift(
                    issue=pr.issue_number,
                    pr=pr.number,
                    pr_commits=commits,
                    issue_label=issue_label,
                    pr_label=pr_pipeline,
                    kind=kind,  # type: ignore[arg-type]
                    detected_at=datetime.now(UTC),
                )
            )
        return out

    async def find_closed_stage_labeled_issues(
        self,
    ) -> list[ClosedStageLabelDrift]:
        """In-memory mirror of :meth:`PRPort.find_closed_stage_labeled_issues`.

        Reports CLOSED issues that still carry an active ``hydraflow-*``
        pipeline-stage label (#10394). Terminal markers (``hydraflow-fixed`` /
        ``hydraflow-verify``) are excluded — they record shipped/verified
        state, mirroring ``HydraFlowConfig.dispatchable_stage_labels``.
        """
        self._maybe_rate_limit()
        out: list[ClosedStageLabelDrift] = []
        for issue in self._issues.values():
            if issue.state != "closed":
                continue
            stale = sorted(
                lbl for lbl in issue.labels if lbl in _DISPATCHABLE_STAGE_LABELS
            )
            if stale:
                out.append(
                    ClosedStageLabelDrift(issue=issue.number, stale_labels=stale)
                )
        return out

    async def list_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        """Return comments seeded on the issue (oldest first).

        FakeIssue.comments stores structured FakeComment records (each a str
        subclass carrying its own login/created_at); this method wraps each
        into a `gh issue view --json comments`-shaped dict so callers (notably
        gather_context, which does `c.get("user", {}).get("login", ...)`)
        operate on dicts as the real PRPort contract requires.
        """
        self._maybe_rate_limit()
        issue = self._issues.get(issue_number)
        if issue is None:
            return []
        return [
            {
                "user": {"login": getattr(comment, "login", "fake-author")},
                "body": str(comment),
                "created_at": getattr(comment, "created_at", "2026-01-01T00:00:00Z"),
            }
            for comment in (getattr(issue, "comments", []) or [])
        ]

    async def get_issue_updated_at(self, issue_number: int) -> str:
        """Return updated_at timestamp for an issue."""
        self._maybe_rate_limit()
        if issue_number in self._issues:
            return getattr(
                self._issues[issue_number], "updated_at", "2026-01-01T00:00:00Z"
            )
        return ""

    async def get_issue_state(self, issue_number: int) -> str:
        """Return issue state as GitHub GraphQL style (OPEN/COMPLETED/NOT_PLANNED).

        An unknown issue returns ``"UNKNOWN"`` — matching prod
        ``PRManager.get_issue_state``, which fail-closes with ``"UNKNOWN"``
        when the ``gh`` read errors. The fake previously fail-opened with
        ``"OPEN"`` here, which made every still-open guard (e.g. the
        refinement TOCTOU stale-close check) pass vacuously for issues the
        fake never saw (#10025).
        """
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            if issue.state == "closed":
                return issue.state_reason or "COMPLETED"
            return "OPEN"
        return "UNKNOWN"

    async def get_issue_labels(self, issue_number: int) -> list[str]:
        """Return the label names on an issue (empty list when unknown)."""
        self._maybe_rate_limit()
        if issue_number in self._issues:
            return list(self._issues[issue_number].labels)
        return []

    async def list_hitl_items(
        self, hitl_labels: list[str], *, concurrency: int = 10
    ) -> list[Any]:
        """Return HITLItem-compatible objects for issues with HITL labels."""
        self._maybe_rate_limit()
        from models import HITLItem

        items: list[HITLItem] = []
        for issue in self._issues.values():
            if issue.state != "open":
                continue
            if any(lbl in issue.labels for lbl in hitl_labels):
                pr = self.pr_for_issue(issue.number)
                items.append(
                    HITLItem(
                        issue=issue.number,
                        title=issue.title,
                        pr=pr.number if pr else 0,
                        branch=pr.branch if pr else "",
                        cause="ci_failure",
                    )
                )
        return items

    async def get_latest_ci_status(self) -> tuple[str, str]:
        """Return (conclusion, url) for latest CI on main branch."""
        self._maybe_rate_limit()
        return self._ci_main_status

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
        **_unused: Any,
    ) -> int:
        """Create a new issue and return its number."""
        self._maybe_rate_limit()
        num = max(self._issues.keys(), default=9000) + 1
        self.add_issue(num, title, body, labels=labels)
        return num

    async def get_dependabot_alerts(self, **_kw: Any) -> list[dict[str, Any]]:
        """Return Dependabot alerts."""
        self._maybe_rate_limit()
        return []

    # --- Additional PRPort methods for port conformance (phase 1) ---

    @staticmethod
    def expected_pr_title(issue_number: int, issue_title: str) -> str:
        """Return the canonical PR title (``Fixes #N: <title>``, truncated).

        Delegates to the real :meth:`PRManager.expected_pr_title` so the fake
        can never drift from production formatting (#10153). FakeGitHub is cast
        to ``PRPort`` in the sandbox harness, so a divergent title here would be
        live-reachable — a fake that lies about the real format.
        """

        return PRManager.expected_pr_title(issue_number, issue_title)

    async def get_pr_mergeable(self, pr_number: int) -> bool | None:
        self._maybe_rate_limit()
        return True

    async def list_conflicting_prs(self) -> list[Any]:
        """Return PRs flagged as conflicting in the fake state."""
        from merge_state_watcher import ConflictingPR  # noqa: PLC0415

        self._maybe_rate_limit()
        results: list[Any] = []
        for pr in self._prs.values():
            if getattr(pr, "mergeable", True):
                continue
            results.append(
                ConflictingPR(
                    number=pr.number,
                    branch=getattr(pr, "head_ref", "") or "",
                    labels=list(getattr(pr, "labels", []) or []),
                )
            )
        return results

    async def pull_main(self, **_kw: Any) -> None:
        self._maybe_rate_limit()

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            self._issues[issue_number].body = body

    async def update_pr_title(self, pr_number: int, title: str) -> bool:
        self._maybe_rate_limit()
        return True

    async def upload_screenshot(self, **_kw: Any) -> str:
        self._maybe_rate_limit()
        return ""

    # --- Staging / RC promotion PRPort methods ---
    #
    # Mirrors the real PRManager semantics (#10309): a "promotion PR" is an
    # open PR whose head branch starts with the RC prefix; the listing methods
    # serve the same projections the real gh-backed reads produce. The prefix
    # matches config's ``rc_branch_prefix`` default — the fake serves one
    # repo's worth of state under default naming, like FakeIssue's fixed
    # timestamps.

    async def create_rc_branch(self, rc_branch: str) -> str:
        self._rc_branches[rc_branch] = _RC_FIXED_DATE
        sha = f"sha-{rc_branch}"
        self._branch_tips[rc_branch] = sha
        return sha

    async def push_synthetic_commit(self, branch: str, message: str) -> str:
        """Record a synthetic commit; deterministic SHA in scenarios."""
        _ = (message,)
        self._maybe_rate_limit()
        sha = f"synthetic-sha-{branch}"
        self._branch_tips[branch] = sha
        return sha

    async def create_promotion_pr(
        self, *, rc_branch: str, title: str, body: str, **_kw: Any
    ) -> int:
        _ = (title, body)
        num = self._pr_counter
        self._pr_counter += 1
        self._prs[num] = FakePR(
            number=num,
            issue_number=0,
            branch=rc_branch,
            draft=False,
            url=f"https://github.com/test/repo/pull/{num}",
        )
        return num

    async def find_open_promotion_pr(self) -> Any:
        """First open ``rc/*`` PR, as PRInfo — the real read's projection."""
        for pr in sorted(self._prs.values(), key=lambda p: p.number):
            if (
                pr.branch.startswith(_RC_BRANCH_PREFIX)
                and not pr.merged
                and not pr.closed
            ):
                return PRInfoFactory.create(
                    number=pr.number,
                    issue_number=0,
                    branch=pr.branch,
                    url=pr.url,
                    draft=pr.draft,
                )
        return None

    async def merge_promotion_pr(self, pr_number: int, **_kw: Any) -> bool:
        pr = self._prs.get(pr_number)
        if pr is not None:
            pr.merged = True
            self._drop_branch_ref_on_merge(pr)
        return True

    async def update_pr_branch(self, pr_number: int, *, method: str = "rebase") -> bool:
        """Fake rebase: clears mergeable flag, always succeeds when PR exists."""
        _ = (method,)
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return False
        pr.mergeable = True
        return True

    async def update_pr_base(self, pr_number: int, *, base: str) -> bool:
        """Fake retarget: records the new base on the in-memory PR."""
        self._maybe_rate_limit()
        if pr_number in self._prs:
            self._prs[pr_number].base = base
            return True
        return False

    async def list_rc_branches(self) -> list[tuple[str, str]]:
        return list(self._rc_branches.items())

    async def delete_branch(self, branch: str) -> bool:
        if branch not in self._branch_tips:
            return False
        del self._branch_tips[branch]
        self._branch_commits.pop(branch, None)
        self._rc_branches.pop(branch, None)
        return True

    async def list_recent_promotion_prs(self, days: int = 7) -> list[dict[str, Any]]:
        """Closed ``rc/*`` PRs in the ``GhPromotionPR`` projection shape."""
        _ = days  # every fake entry is "recent" — fixed dates, no wall clock
        return [
            {
                "number": pr.number,
                "branch": pr.branch,
                "merged": pr.merged,
                "closed_at": _RC_FIXED_DATE,
                "url": pr.url,
            }
            for pr in sorted(self._prs.values(), key=lambda p: p.number)
            if pr.branch.startswith(_RC_BRANCH_PREFIX) and (pr.merged or pr.closed)
        ]

    async def ensure_branch_exists(self, branch: str, *, base: str) -> bool:
        _ = base
        # Models the steady state (branch already present): always False,
        # but the branch is guaranteed to exist afterward either way, so a
        # missing tip is created without clobbering one already tracked.
        self._branch_tips.setdefault(branch, f"sha-{branch}")
        return False

    async def apply_staging_branch_protection(self, branch: str) -> dict[str, Any]:
        return {"status": "protected", "branch": branch}

    def fetch_rulesets(self, repo: str) -> dict[str, dict[str, Any]]:
        """Serve seeded branch-protection rulesets, keyed by ruleset name.

        Sync mirror of ``branch_protection_audit.gh_fetch_rulesets`` (which
        shells out to ``gh api /repos/{repo}/rulesets``). Injectable verbatim
        as the ``fetch_rulesets=`` seam of ``branch_protection_audit.audit_repo``
        so a sandbox / scenario ``branch_protection_auditor`` run observes drift
        against the canonical contract without a real network fetch — the seam
        the s41 scenario needs (#9644, ADR-0082).

        ``repo`` is accepted for signature parity with ``gh_fetch_rulesets`` but
        ignored: the Fake serves one repo's worth of seeded state. Returns a
        deep copy so a caller mutating the result cannot corrupt seeded state.
        """
        _ = repo
        return copy.deepcopy(self._rulesets)

    def fetch_legacy_protection(self, repo: str, branch: str) -> dict[str, Any] | None:
        """Serve seeded classic branch-protection config for one branch.

        Sync mirror of ``branch_protection_audit.gh_fetch_legacy_protection``
        (which shells out to ``gh api /repos/{repo}/branches/{branch}/
        protection``, 404-ing to ``None`` when no classic rule exists).
        Injectable verbatim as the ``fetch_legacy_protection=`` seam of
        ``branch_protection_audit.audit_repo`` so a sandbox / scenario
        ``branch_protection_auditor`` run can observe an undeclared
        legacy-layer drift without a real network fetch (#10148).

        ``repo`` is accepted for signature parity with
        ``gh_fetch_legacy_protection`` but ignored: the Fake serves one
        repo's worth of seeded state. Returns a deep copy so a caller
        mutating the result cannot corrupt seeded state. ``None`` (not an
        empty dict) when ``branch`` was never seeded — matches the raw
        fetcher's "no classic rule" return.
        """
        _ = repo
        protection = self._legacy_protection.get(branch)
        return copy.deepcopy(protection) if protection is not None else None

    # --- Concrete-only PRManager methods invoked at orchestrator boot ---

    async def ensure_labels_exist(self) -> None:
        """Idempotently create HydraFlow lifecycle labels (no-op stub).

        Production PRManager pushes label definitions to GitHub via
        ``gh label create``. The seeded FakeGitHub already has whatever
        labels the seed declared, so this is a no-op. Required because
        ``HydraFlowOrchestrator.run()`` calls ``prs.ensure_labels_exist()``
        unconditionally during pipeline boot.
        """
        return None

    async def get_label_counts(self, config: Any) -> dict[str, Any]:
        """Return open-by-label / total-closed / total-merged counts.

        Mirrors ``PRManager.get_label_counts``. Used by ``GitHubCacheLoop``
        to pre-warm the dashboard's "throughput" tile. The Fake walks
        ``_issues`` for open counts and ``_prs`` for merged counts.
        """
        self._maybe_rate_limit()
        label_map = {
            "hydraflow-plan": getattr(config, "planner_label", ["hydraflow-plan"]),
            "hydraflow-ready": getattr(config, "ready_label", ["hydraflow-ready"]),
            "hydraflow-review": getattr(config, "review_label", ["hydraflow-review"]),
            "hydraflow-hitl": getattr(config, "hitl_label", ["hydraflow-hitl"]),
            "hydraflow-fixed": getattr(config, "fixed_label", ["hydraflow-fixed"]),
        }
        open_by_label: dict[str, int] = {}
        for canonical, labels in label_map.items():
            wanted = set(labels) if isinstance(labels, list) else {labels}
            count = sum(
                1
                for issue in self._issues.values()
                if issue.state == "open" and (set(issue.labels) & wanted)
            )
            open_by_label[canonical] = count

        fixed_label = (
            getattr(config, "fixed_label", ["hydraflow-fixed"])[0]
            if getattr(config, "fixed_label", None)
            else "hydraflow-fixed"
        )
        total_closed = sum(
            1
            for issue in self._issues.values()
            if issue.state != "open" and fixed_label in issue.labels
        )
        total_merged = sum(1 for pr in self._prs.values() if pr.merged)

        return {
            "open_by_label": open_by_label,
            "total_closed": total_closed,
            "total_merged": total_merged,
        }

    async def list_open_prs(self, labels: list[str]) -> list[Any]:
        """Return open PRs carrying any of *labels* as PRListItem-style objects.

        Mirrors ``PRManager.list_open_prs``. Used by ``GitHubCacheLoop`` to
        warm its PR-by-label cache. The Fake walks ``_prs`` filtered by
        ``merged=False`` and label intersection.
        """
        self._maybe_rate_limit()
        from models import PRListItem

        wanted = set(labels)
        out: list[PRListItem] = []
        for pr in self._prs.values():
            if pr.merged:
                continue
            if wanted and not (wanted & set(pr.labels)):
                continue
            out.append(
                PRListItem(
                    pr=pr.number,
                    issue=pr.issue_number,
                    branch=pr.branch,
                    url=pr.url or "",
                    draft=pr.draft,
                    title="",
                    merged=pr.merged,
                    author=pr.author,
                    is_bot=pr.is_bot,
                )
            )
        return out

    async def list_all_open_prs(self) -> list[Any]:
        """Return ALL open PRs regardless of label, including author login.

        Mirrors ``PRManager.list_all_open_prs``. Used by ``GitHubCacheLoop``
        to warm the all-open-PRs snapshot that ``DependabotMergeLoop`` reads
        (it filters by author). Bot PRs carry only GitHub-native labels like
        ``dependencies`` and are invisible to the label-filtered
        ``list_open_prs`` cache — this method does not filter by label.
        """
        self._maybe_rate_limit()
        from models import PRListItem

        return [
            PRListItem(
                pr=pr.number,
                issue=pr.issue_number,
                branch=pr.branch,
                url=pr.url or "",
                draft=pr.draft,
                title="",
                merged=pr.merged,
                author=pr.author,
                is_bot=pr.is_bot,
            )
            for pr in self._prs.values()
            if not pr.merged
        ]

    async def _run_gh(self, *cmd: str, cwd: Any = None) -> str:
        """Generic ``gh`` CLI passthrough — returns minimal-shape JSON.

        Production ``PRManager._run_gh`` exec's the ``gh`` CLI and returns
        stdout. The Fake parses *cmd* far enough to identify which API
        call it represents (``gh issue list``, ``gh pr list``, etc.) and
        synthesizes a JSON payload from in-memory state.

        Unknown commands return ``"[]"`` rather than raising — keeps
        loops that probe rare endpoints quiet during scenario runs.
        """
        self._maybe_rate_limit()
        _ = cwd
        import json as _json

        args = list(cmd)
        # Strip leading "gh" if the caller included it (some sites do).
        if args and args[0] == "gh":
            args = args[1:]
        if not args:
            return "[]"

        verb = args[0]

        if verb == "issue" and len(args) > 1:
            issue_read = await self._run_gh_issue_read(args)
            if issue_read is not None:
                return issue_read

        if verb == "pr" and len(args) > 1:
            sub = args[1]
            if sub == "list":
                payload = [
                    {
                        "number": pr.number,
                        "title": "",
                        "url": pr.url or "",
                        "labels": [{"name": lbl} for lbl in pr.labels],
                    }
                    for pr in self._prs.values()
                    if not pr.merged
                ]
                return _json.dumps(payload)

        if verb == "api" and len(args) > 1:
            branch_read = self._run_gh_branch_read(args)
            if branch_read is not None:
                return branch_read

        # Unknown verb: return empty JSON array — safe default for
        # callers that ``json.loads`` the output.
        return "[]"

    async def _run_gh_issue_read(self, args: list[str]) -> str | None:
        """Serve the ``gh issue <sub>`` shapes StaleIssueLoop's generic
        auto-close sweep and close path use. Returns ``None`` when *args*
        isn't one of the recognized ``list``/``close``/``view`` shapes, so
        ``_run_gh`` falls through to its generic unknown-verb default.
        """
        import json as _json

        sub = args[1]
        if sub == "list":
            # Minimally-shaped issue list. StaleIssueLoop expects
            # number/title/updatedAt/labels.
            payload = [
                {
                    "number": issue.number,
                    "title": issue.title,
                    "updatedAt": getattr(issue, "updated_at", "2026-01-01T00:00:00Z"),
                    "labels": [{"name": lbl} for lbl in issue.labels],
                }
                for issue in self._issues.values()
                if issue.state == "open"
            ]
            return _json.dumps(payload)
        if sub == "close":
            # Best-effort: extract issue number from positional args.
            for a in args[2:]:
                if a.isdigit():
                    await self.close_issue(int(a))
                    break
            return ""
        if sub == "view":
            return _json.dumps({"comments": []})
        return None

    def _run_gh_branch_read(self, args: list[str]) -> str | None:
        """Serve the two ``gh api`` branch reads StaleIssueLoop's branch-GC
        composes (#11227), off live ``_branch_tips``/``_branch_commits``
        state in their post-``--jq`` shapes. Returns ``None`` when *args*
        isn't one of the two recognized branch-read shapes, so ``_run_gh``
        falls through to its generic unknown-verb default.
        """
        import json as _json

        path = args[1]
        # StaleIssueLoop._branch_gc_candidate_branches: matching-refs.
        if "/git/matching-refs/heads/" in path:
            prefix = path.split("/git/matching-refs/heads/", 1)[1]
            refs = sorted(
                f"refs/heads/{b}" for b in self._branch_tips if b.startswith(prefix)
            )
            return _json.dumps(refs)
        # StaleIssueLoop._branch_gc_commit_info: commits (newest-first).
        if path.endswith("/commits"):
            branch = ""
            for i, a in enumerate(args):
                if (
                    a == "--field"
                    and i + 1 < len(args)
                    and args[i + 1].startswith("sha=")
                ):
                    branch = args[i + 1].removeprefix("sha=")
                    break
            info = self._branch_commits.get(branch)
            if info is None or not info[1]:
                return "[]"
            last_commit_iso, messages = info
            payload = [{"date": last_commit_iso, "message": messages[0]}]
            payload.extend({"date": "", "message": m} for m in messages[1:])
            return _json.dumps(payload)
        return None
