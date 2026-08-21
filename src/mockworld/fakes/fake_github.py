"""Stateful GitHub fake for scenario testing.

Tracks issues (labels, state, comments) and PRs (merged, CI status)
as in-memory state. Implements the async PRManager interface methods
that phases call via PipelineHarness.
"""

from __future__ import annotations

import copy
import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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
_GIT_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


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
    # gh's createdAt (#11418) — the fitness fetcher and StaleIssueLoop's
    # backlog-budget valve key issue age off this field. Defaults alongside
    # updated_at so pre-#11418 seeds are unaffected.
    created_at: str = "2026-01-01T00:00:00Z"
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
    # Historical PR HEAD identity. Branch names can be reused; destructive
    # consumers must match this SHA as well as ``branch`` (#11502).
    head_sha: str = ""
    base_branch: str = "main"
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
    # gh's createdAt (#11418) — list_all_prs / the fitness fetcher key PR
    # age off this field. Defaults to the same fixed date as before #11418
    # (list_all_prs stamped every PR with it unconditionally) so unseeded
    # PRs are unaffected; add_pr(created_at=...) lets a scenario seed
    # distinct ages for window-boundary testing.
    created_at: str = _RC_FIXED_DATE
    # Only meaningful once closed/merged; mirrors gh's closedAt/mergedAt.
    # Empty = "not explicitly seeded" — list_all_prs falls back to
    # created_at, mirroring FakeIssue.closed_at's convention (#9727).
    closed_at: str = ""
    merged_at: str = ""
    # The PR's own declaration of what it closes (#11480). Production PR
    # titles are ``Fixes #N: <title>``; the decompose terminal reads these
    # to tell a landing fix from a stalled one. Empty by default so an
    # unseeded PR declares nothing — a scenario must opt in explicitly.
    title: str = ""
    body: str = ""


class FakeGitHubUnmodelledCommand(RuntimeError):
    """Raised when ``_run_gh`` sees a shape the fake does not model.

    Fail-loud replaces the old silent ``"[]"`` (#11372) so a fidelity gap
    surfaces as a stack at the call site instead of a passing scenario.
    """


#: ``gh`` command prefixes that may legitimately answer empty in the
#: sandbox. Each entry needs a one-line reason; keep this list SHORT —
#: modelling the command is the real fix.
_QUIET_UNKNOWN_GH_SHAPES: tuple[str, ...] = (
    # Rate-limit / auth probes: sandbox scenarios never assert on them and
    # the real answers are environmental, not pipeline state.
    "api rate_limit",
    "auth status",
)


class FakeGitHub:
    """Stateful fake for GitHub API (PRManager + IssueFetcher)."""

    _is_fake_adapter = True  # read by dashboard for MOCKWORLD banner

    def __init__(self) -> None:
        self._issues: dict[int, FakeIssue] = {}
        # #11246: `gh issue view --json` fields the fake was asked for but
        # does not model. Recorded instead of fabricated so scenarios can
        # surface fake-fidelity gaps (matched-but-wrong shapes are invisible
        # to strict-mode shape checks).
        self.issue_view_unmodelled_fields: set[str] = set()
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
        # #11418: seeded remote branches for StaleIssueLoop's branch-GC scan
        # (agent/issue-*, fix/* by default) — branch name → commit history,
        # newest first. Distinct from _rc_branches (rc/* has its own
        # lifecycle via create_rc_branch/delete_branch).
        self._branch_commits: dict[str, list[dict[str, str]]] = {}
        # #11517: release tagging (ADR-0011). ``_branch_heads`` seeds what
        # ``resolve_remote_branch_sha`` answers per branch (``None`` = the
        # branch cannot be resolved, driving the fail-closed skip); unseeded
        # branches resolve to the synthetic ``sha-<branch>`` that
        # ``list_branch_refs`` also reports. ``_tags`` / ``_releases`` record
        # create_tag / create_release so scenarios can assert the tag ref.
        self._branch_heads: dict[str, str | None] = {}
        self._tags: dict[str, str] = {}
        self._releases: dict[str, tuple[str, str]] = {}
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
                created_at=issue_dict.get("created_at"),
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
        created_at: str | None = None,
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
        if created_at:
            issue.created_at = created_at
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
        head_sha: str = "",
        base_branch: str = "main",
        ci_status: str = "pass",
        merged: bool = False,
        author: str = "fake-author",
        is_bot: bool = False,
        mergeable: bool = True,
        created_at: str | None = None,
        closed_at: str | None = None,
        merged_at: str | None = None,
        title: str = "",
        body: str = "",
        checks: list[tuple[str, str]] | None = None,
    ) -> None:
        """Directly insert a PR record (sync helper for test seeding).

        The async ``create_pr`` handles the production path; this helper
        exists so scenario seeds can set up a fully-populated world
        synchronously. ``mergeable=False`` seeds a CONFLICTING PR that
        ``list_conflicting_prs`` surfaces to merge_state_watcher (#9543).
        ``created_at``/``closed_at``/``merged_at`` let a scenario give
        distinct PRs distinct ages for fitness-window boundary testing
        (#11418) — unset, they fall back to FakePR's fixed defaults.
        ``title``/``body``/``checks`` seed what ``get_pr_title_and_body`` and
        ``get_pr_checks`` serve, so a scenario can stage a PR that declares
        ``Fixes #N`` with live CI (#11480).
        """
        pr = FakePR(
            number=number,
            issue_number=issue_number,
            branch=branch,
            head_sha=head_sha,
            base_branch=base_branch,
            merged=merged,
            ci_status=ci_status,
            author=author,
            is_bot=is_bot,
            mergeable=mergeable,
            title=title,
            body=body,
            checks=list(checks or []),
        )
        if created_at:
            pr.created_at = created_at
        if closed_at:
            pr.closed_at = closed_at
        if merged_at:
            pr.merged_at = merged_at
        self._prs[number] = pr

    def add_pr_label(self, pr_number: int, label: str) -> None:
        """Seed-API helper: attach a label to a fake PR."""
        if pr_number not in self._prs:
            raise KeyError(f"FakeGitHub: no PR {pr_number}")
        pr = self._prs[pr_number]
        if label not in pr.labels:
            pr.labels.append(label)

    def add_gc_branch(
        self, branch: str, commits: list[dict[str, str]] | None = None
    ) -> None:
        """Seed-API helper: register a remote branch for branch-GC scenarios (#11418).

        *commits* is ``[{"date": iso, "message": msg}, ...]`` newest first.
        Defaults to one synthetic commit dated 2026-01-01 — enough for
        ``StaleIssueLoop``'s branch-GC to age the branch and (if *branch*
        follows the ``agent/issue-<n>`` naming convention) resolve the
        issue it references.
        """
        self._branch_commits[branch] = commits or [
            {"date": "2026-01-01T00:00:00Z", "message": f"chore: seed {branch}"}
        ]

    def set_branch_head(self, branch: str, sha: str | None) -> None:
        """Seed-API helper: pin what ``resolve_remote_branch_sha`` returns (#11517).

        ``None`` marks *branch* unresolvable (a fetch / rev-parse failure),
        so a scenario can prove the release path skips fail-closed instead
        of falling back to the checkout ``HEAD``.
        """
        self._branch_heads[branch] = sha

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
        *args: Any,
        **_kwargs: Any,
    ) -> bool:
        self._maybe_rate_limit()
        _ = args
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
        # Slug matches the recorded pr_create cassette (test-org/test-repo) —
        # the contract replay normalizes the number but NOT the repo slug.
        url = f"https://github.com/test-org/test-repo/pull/{number}"
        self._prs[number] = FakePR(
            number=number,
            issue_number=issue_number,
            branch=branch,
            draft=draft,
            url=url,
        )
        # Return the URL the fake actually stores — production ``PRInfo.url``
        # is the created PR's URL, and the light-lane spawn seam renders it
        # into the ``<pr_url>`` tag the auto-agent decision parses (#11298).
        return PRInfoFactory.create(
            number=number,
            issue_number=issue_number,
            branch=branch,
            draft=draft,
            url=url,
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

    async def get_branch_pr_state(
        self, branch: str, head_sha: str, base_branch: str
    ) -> str:
        """Mirror production's exact-HEAD historical PR lookup (#11502).

        A merged PR on a reused branch is deliberately ignored unless its
        seeded base and ``head_sha`` match the caller's current integration
        target and HEAD. Multiple exact matches are ambiguous and fail closed.
        """
        self._maybe_rate_limit()
        normalized_branch = branch.removeprefix("refs/heads/")
        normalized_sha = head_sha.strip().lower()
        normalized_base = base_branch.removeprefix("refs/heads/")
        if (
            not normalized_branch
            or _GIT_OID_RE.fullmatch(normalized_sha) is None
            or not normalized_base
        ):
            return "UNKNOWN"
        matches = [
            pr
            for pr in self._prs.values()
            if pr.branch == normalized_branch
            and pr.head_sha.lower() == normalized_sha
            and pr.base_branch == normalized_base
        ]
        if not matches:
            return "NONE"
        if len(matches) != 1:
            return "UNKNOWN"
        pr = matches[0]
        if pr.merged:
            return "MERGED"
        return "CLOSED" if pr.closed else "OPEN"

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

    async def get_pr_title_and_body(self, pr_number: int) -> tuple[str, str]:
        """Serve seeded ``FakePR.title``/``FakePR.body`` (#11480).

        Defaults to ``("", "")`` — the same "unreadable" shape the real
        adapter returns on failure — so an unseeded PR never accidentally
        declares a closing keyword for its issue.
        """
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return ("", "")
        return (pr.title, pr.body)

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
        if pr_number in self._prs:
            self._prs[pr_number].merged = True
        return True

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
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return closed issues carrying *label* (most recent up to *limit*).

        ``closed_at`` mirrors the adapter's ``closedAt`` projection (#9727)
        so churn windows keyed on close time behave identically under the
        fake and the real port. ``labels`` (#8996) reuses ``_issue_summary``
        so ``escalation_reconcile.is_bot_close`` sees the same gh-wire-shape
        label list under the fake as under the real adapter.

        ``limit`` stays positional-or-keyword (#11423) — matching
        ``PRPort.list_closed_issues_by_label`` and the ``PRManager``
        adapter, both of which permit ``list_closed_issues_by_label(label,
        limit)`` as a fully positional call.
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

    async def get_issue_body(self, issue_number: int) -> str:
        """Return the body text of an issue (empty string when unknown)."""
        self._maybe_rate_limit()
        issue = self._issues.get(issue_number)
        return issue.body if issue is not None else ""

    async def list_all_issues(
        self, *, state: str = "all", limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return issues in *state* as raw gh-wire dicts (#11418).

        Mirrors ``PRManager.list_all_issues``' field shape: number, title,
        state, labels, createdAt, updatedAt, closedAt.
        """
        self._maybe_rate_limit()
        wanted = {"open", "closed"} if state == "all" else {state.lower()}
        items = [
            {
                "number": issue.number,
                "title": issue.title,
                "state": issue.state.upper(),
                "labels": [{"name": lbl} for lbl in issue.labels],
                "createdAt": issue.created_at,
                "updatedAt": issue.updated_at,
                "closedAt": issue.closed_at or None,
            }
            for issue in self._issues.values()
            if issue.state in wanted
        ]
        return items[:limit]

    async def list_all_prs(
        self, *, state: str = "all", limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return PRs in *state* as raw gh-wire dicts (#11418).

        Mirrors ``PRManager.list_all_prs``' field shape: number, state,
        labels, createdAt, closedAt, mergedAt.
        """
        self._maybe_rate_limit()

        def _pr_state(pr: FakePR) -> str:
            if pr.merged:
                return "merged"
            if pr.closed:
                return "closed"
            return "open"

        wanted = None if state == "all" else state.lower()
        items = []
        for pr in self._prs.values():
            pr_state = _pr_state(pr)
            if wanted is not None and pr_state != wanted:
                continue
            items.append(
                {
                    "number": pr.number,
                    "state": pr_state.upper(),
                    "labels": [{"name": lbl} for lbl in pr.labels],
                    "createdAt": pr.created_at,
                    "closedAt": (pr.closed_at or pr.created_at)
                    if pr_state != "open"
                    else None,
                    "mergedAt": (pr.merged_at or pr.created_at) if pr.merged else None,
                }
            )
        return items[:limit]

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
                    # FakePR's field is ``branch`` (mirrors headRefName). The
                    # old ``getattr(pr, "head_ref", "")`` read a field that
                    # never existed, so every conflicting PR came back with an
                    # empty branch — masked until the auto-rebase actuator
                    # (#11595) made the head-branch namespace load-bearing.
                    branch=pr.branch or "",
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

    # --- Release tagging (ADR-0011, #11517) ---
    #
    # Mirrors PRManager.resolve_remote_branch_sha / create_tag /
    # create_release: the epic release path resolves the promoted main SHA
    # (ADR-0042) and tags THAT, never the factory checkout HEAD. The fake
    # records the ``tag -> ref`` pairing so scenarios can assert the target.

    async def resolve_remote_branch_sha(self, branch: str) -> str | None:
        """Seeded head for *branch* (``None`` = unresolvable), else ``sha-<branch>``."""
        self._maybe_rate_limit()
        if branch in self._branch_heads:
            return self._branch_heads[branch]
        return f"sha-{branch}"

    async def create_tag(self, tag: str, *, ref: str) -> bool:
        """Record *tag* -> *ref*; a duplicate tag fails like ``git tag`` does."""
        self._maybe_rate_limit()
        if tag in self._tags:
            return False
        self._tags[tag] = ref
        return True

    async def create_release(self, tag: str, title: str, body: str) -> bool:
        """Record the GitHub Release for *tag*."""
        self._maybe_rate_limit()
        self._releases[tag] = (title, body)
        return True

    @property
    def tags(self) -> dict[str, str]:
        """``{tag: ref}`` recorded by :meth:`create_tag` (a copy)."""
        return dict(self._tags)

    @property
    def releases(self) -> dict[str, tuple[str, str]]:
        """``{tag: (title, body)}`` recorded by :meth:`create_release` (a copy)."""
        return dict(self._releases)

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
        return f"sha-{rc_branch}"

    async def push_synthetic_commit(self, branch: str, message: str) -> str:
        """Record a synthetic commit; deterministic SHA in scenarios."""
        _ = (message,)
        self._maybe_rate_limit()
        return f"synthetic-sha-{branch}"

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
        if pr_number in self._prs:
            self._prs[pr_number].merged = True
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

    async def list_branch_refs(self, prefix: str) -> list[tuple[str, str]]:
        """Return ``[(branch_name, sha), ...]`` for ``refs/heads/<prefix>*`` (#11418).

        Searches every branch namespace the fake tracks — seeded GC
        branches (``add_gc_branch``), rc/* branches, and open PR head
        branches — mirroring the real ``matching-refs`` API, which is not
        scoped to any one branch lifecycle. The sha is synthetic
        (``sha-<branch>``); nothing in the fake resolves it back to a real
        commit — :meth:`list_branch_commits` looks commits up by branch
        name directly.
        """
        self._maybe_rate_limit()
        branch_names = (
            set(self._branch_commits)
            | set(self._rc_branches)
            | {pr.branch for pr in self._prs.values() if pr.branch}
        )
        return [
            (branch, f"sha-{branch}")
            for branch in sorted(branch_names)
            if branch.startswith(prefix)
        ]

    async def list_branch_commits(
        self, branch: str, *, limit: int = 30
    ) -> list[dict[str, str]]:
        """Return seeded commit history for *branch*, newest first (#11418).

        Empty when *branch* was never seeded via :meth:`add_gc_branch` —
        a scenario must explicitly seed the commit history it wants
        StaleIssueLoop's branch-GC to discover, mirroring the
        ``add_issue``/``add_pr`` seed-explicitly convention.
        """
        self._maybe_rate_limit()
        commits = self._branch_commits.get(branch, [])
        return [dict(c) for c in commits[:limit]]

    async def delete_branch(self, branch: str) -> bool:
        self._rc_branches.pop(branch, None)
        self._branch_commits.pop(branch, None)
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
        _ = (branch, base)
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

    def _modelled_api_payload(self, path: str) -> str | None:
        """Payloads for the ``gh api`` shapes real loops call (#11413).

        StaleIssueLoop's branch-GC makes both of these live — the sampled
        re-audit of #11372 falsified that PR's "no loop relied on the
        silent empty answer" claim by finding them. They are MODELLED, not
        allowlisted quiet: allowlisting would reintroduce exactly the blind
        spot fail-loud exists to remove. ``None`` means "not modelled here".
        """
        if "/git/matching-refs/heads/" in path:
            prefix = path.rsplit("/heads/", 1)[-1]
            return json.dumps(
                [
                    f"refs/heads/{pr.branch}"
                    for pr in self._prs.values()
                    if pr.branch and pr.branch.startswith(prefix)
                ]
            )
        if path.endswith("/commits"):
            # The loop reads only the newest commit's date/sha to age a
            # branch; an empty list is the honest "no commits recorded".
            return json.dumps([])
        return None

    @staticmethod
    def _option_value(args: list[str], option: str) -> str | None:
        """Return the value following *option*, or ``None`` when absent."""
        if option not in args:
            return None
        value_index = args.index(option) + 1
        return args[value_index] if value_index < len(args) else None

    @staticmethod
    def _option_values(args: list[str], option: str) -> list[str]:
        """Return every value supplied for a repeatable CLI *option*."""
        return [
            args[index + 1]
            for index, argument in enumerate(args[:-1])
            if argument == option
        ]

    def _issue_edit_body(self, args: list[str]) -> str | None:
        """Read the body-file value, falling back to an inline body."""
        path = self._option_value(args, "--body-file")
        if path is not None:
            try:
                return Path(path).read_text(encoding="utf-8")
            except OSError:
                pass
        return self._option_value(args, "--body")

    @classmethod
    def _issue_view_fields(cls, args: list[str]) -> tuple[list[str], list[str]]:
        """Return raw selectors and their ordered, de-duplicated field union."""
        selectors = cls._option_values(args, "--json")
        fields = [
            field.strip()
            for selector in selectors
            for field in selector.split(",")
            if field.strip()
        ]
        return selectors, list(dict.fromkeys(fields))

    @staticmethod
    def _issue_view_projections(issue: FakeIssue) -> dict[str, Any]:
        """Return every FakeIssue field modelled by the gh view boundary."""
        state_reason = issue.state_reason or (
            "COMPLETED" if issue.state == "closed" else ""
        )
        comments = [
            {
                "author": {"login": comment.login},
                "body": str(comment),
                "createdAt": comment.created_at,
            }
            for comment in issue.comments
        ]
        return {
            "number": issue.number,
            "labels": [{"name": label} for label in issue.labels],
            "body": issue.body,
            "title": issue.title,
            "state": issue.state.upper(),
            "stateReason": state_reason,
            "updatedAt": issue.updated_at,
            "comments": comments,
        }

    async def _handle_issue_edit(self, args: list[str]) -> None:
        """Model ``gh issue edit <n> --body-file <path>`` / ``--body <text>``.

        The production issuer is ``PRManager.update_issue_body``, which sends
        the body through a temp ``--body-file`` (``_run_with_body_file``)
        (#11419) — the fake reads the same file the real CLI would. Inline
        ``--body <text>`` (#11246) covers direct CLI callers so a
        passthrough-routed repair is observable in fake state too.
        Best-effort: extracts the issue number (first digit-only positional)
        and the body from either flag (``--body-file`` wins if both appear),
        then delegates to :meth:`update_issue_body` so the CLI route and the
        Port-method route end up in the same place. A missing file, a
        valueless flag, or an edit without a body flag (e.g. label-only
        edits) is a no-op.
        """
        number = next((int(a) for a in args[2:] if a.isdigit()), None)
        body = self._issue_edit_body(args)
        if number is None or body is None:
            return
        if number not in self._issues:
            raise RuntimeError(f"FakeGitHub: issue {number} not found")
        await self.update_issue_body(number, body)

    def _render_issue_view(self, args: list[str]) -> str:
        """Project requested ``gh issue view --json`` fields from fake state.

        The old dispatcher returned a hardcoded ``{"comments": []}`` for
        every selector. That matched the command while silently giving
        consumers the wrong shape. Unsupported fields are deliberately
        omitted and recorded instead of fabricated (#11246).
        """
        issue_number = next((int(a) for a in args[2:] if a.isdigit()), 0)
        selectors, fields = self._issue_view_fields(args)
        issue = self._issues.get(issue_number)
        if issue is None:
            raise RuntimeError(f"FakeGitHub: issue {issue_number} not found")

        if not selectors:
            self.issue_view_unmodelled_fields.add("--json")
        if "--jq" in args:
            self.issue_view_unmodelled_fields.add("--jq")

        projections = self._issue_view_projections(issue)
        payload: dict[str, Any] = {}
        for field_name in fields:
            if field_name in projections:
                payload[field_name] = projections[field_name]
            else:
                self.issue_view_unmodelled_fields.add(field_name)
        return json.dumps(payload)

    async def _run_gh(self, *cmd: str, cwd: Any = None) -> str:
        """Generic ``gh`` CLI passthrough — returns minimal-shape JSON.

        Production ``PRManager._run_gh`` exec's the ``gh`` CLI and returns
        stdout. The Fake parses *cmd* far enough to identify which API
        call it represents (``gh issue list``, ``gh pr list``, etc.) and
        synthesizes a JSON payload from in-memory state.

        Unknown commands RAISE (#11372) unless the shape is explicitly
        allowlisted in :data:`_QUIET_UNKNOWN_GH_SHAPES`. The old silent
        ``"[]"`` made every fidelity gap invisible: a loop probing an
        unmodelled endpoint got a plausible empty answer, its scenario
        passed, and the real adapter's behaviour was never exercised —
        the gaps were then discovered one at a time by the fake-coverage
        auditor and filed as separate issues. Failing loud converts that
        class from "discovered one escape at a time" to "enumerated once,
        at the call".
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
            sub = args[1]
            if sub == "list":
                # Return minimally-shaped issue list. StaleIssueLoop expects
                # number/title/updatedAt/labels.
                payload = [
                    {
                        "number": issue.number,
                        "title": issue.title,
                        "updatedAt": getattr(
                            issue, "updated_at", "2026-01-01T00:00:00Z"
                        ),
                        "labels": [{"name": lbl} for lbl in issue.labels],
                    }
                    for issue in self._issues.values()
                    if issue.state == "open"
                ]
                return _json.dumps(payload)
            if sub in ("close", "edit"):
                if sub == "close":
                    # Best-effort: extract issue number from positional args.
                    for a in args[2:]:
                        if a.isdigit():
                            await self.close_issue(int(a))
                            break
                else:
                    await self._handle_issue_edit(args)
                return ""
            if sub == "view":
                return self._render_issue_view(args)

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

        # Unknown shape: FAIL LOUD (#11372). Quiet shapes are allowlisted
        # above; anything else is a fidelity gap the scenario would
        # otherwise paper over with a plausible empty answer.
        # Modelled `gh api` shapes (#11413) and the quiet allowlist share one
        # exit so the dispatcher keeps a single fall-through.
        modelled = (
            self._modelled_api_payload(args[1])
            if verb == "api" and len(args) > 1
            else None
        )
        shape = " ".join(args[:3])
        quiet = any(shape.startswith(prefix) for prefix in _QUIET_UNKNOWN_GH_SHAPES)
        if modelled is not None or quiet:
            return modelled if modelled is not None else "[]"
        raise FakeGitHubUnmodelledCommand(
            f"FakeGitHub has no model for `gh {' '.join(args)}`. Either model "
            "the command (preferred — that is the fidelity fix) or, if the "
            "caller genuinely tolerates an empty answer in the sandbox, add "
            "its prefix to _QUIET_UNKNOWN_GH_SHAPES with a one-line reason. "
            "Do NOT reintroduce a blanket empty default (#11372)."
        )
