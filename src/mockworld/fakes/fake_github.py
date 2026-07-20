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
from models import LabelDrift

if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed


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


class FakeGitHub:
    """Stateful fake for GitHub API (PRManager + IssueFetcher)."""

    _is_fake_adapter = True  # read by dashboard for MOCKWORLD banner

    def __init__(self) -> None:
        self._issues: dict[int, FakeIssue] = {}
        self._pr_diff_names: dict[int, list[str]] = {}
        # #9974: seeded workflow-run history for GateHealthLoop scenarios.
        self._workflow_runs: list[dict[str, Any]] = []
        self._workflow_jobs: dict[int, list[dict[str, Any]]] = {}
        self._workflow_artifacts: dict[int, int] = {}
        self._prs: dict[int, FakePR] = {}
        self._pr_counter = 10_000
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
    ) -> None:
        self._issues[number] = FakeIssue(
            number=number,
            title=title,
            body=body,
            labels=labels or [],
        )

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
    ) -> None:
        """Directly insert a PR record (sync helper for test seeding).

        The async ``create_pr`` handles the production path; this helper
        exists so scenario seeds can set up a fully-populated world
        synchronously.
        """
        self._prs[number] = FakePR(
            number=number,
            issue_number=issue_number,
            branch=branch,
            merged=merged,
            ci_status=ci_status,
            author=author,
            is_bot=is_bot,
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
            "discover": "hydraflow-discover",
            "shape": "hydraflow-shape",
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
        self._prs[number] = FakePR(
            number=number,
            issue_number=issue_number,
            branch=branch,
            draft=draft,
            url=f"https://github.com/test/repo/pull/{number}",
        )
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

    def set_pr_diff_names(self, pr_number: int, names: list[str]) -> None:
        """Seed the changed-file list one PR reports (#9974 blame scenarios)."""
        self._pr_diff_names[pr_number] = list(names)

    async def get_pr_diff_names(self, pr_number: int) -> list[str]:
        self._maybe_rate_limit()
        return list(self._pr_diff_names.get(pr_number, ["src/app.py"]))

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
        """No CI checks in the air-gapped sandbox. Empty is falsy, so epic
        detail rendering (EpicManager._enrich_pr_status) derives no CI status
        rather than AttributeError-ing — which previously dropped any epic with
        a PR'd child from /api/epics."""
        self._maybe_rate_limit()
        return []

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
        conclusion: str,
        created_at: str = "2026-07-01T00:00:00Z",
        pr_number: int = 0,
        jobs: list[dict[str, Any]] | None = None,
        artifact_count: int = 0,
    ) -> None:
        """Seed one workflow run (+jobs/artifacts) for gate-health scenarios."""
        self._workflow_runs.append(
            {
                "id": run_id,
                "workflow": workflow,
                "conclusion": conclusion,
                "created_at": created_at,
                "pr_number": pr_number,
            }
        )
        self._workflow_jobs[run_id] = jobs or []
        self._workflow_artifacts[run_id] = artifact_count

    async def list_workflow_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest-first slice of the seeded run history (#9974)."""
        self._maybe_rate_limit()
        newest_first = sorted(
            self._workflow_runs, key=lambda r: str(r["created_at"]), reverse=True
        )
        return [dict(r) for r in newest_first[:limit]]

    async def get_workflow_run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        self._maybe_rate_limit()
        return [dict(j) for j in self._workflow_jobs.get(run_id, [])]

    async def count_workflow_run_artifacts(self, run_id: int) -> int:
        self._maybe_rate_limit()
        return self._workflow_artifacts.get(run_id, 0)

    async def list_closed_issues_by_label(
        self,
        label: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return closed issues carrying *label* (most recent up to *limit*).

        ``closed_at`` mirrors the adapter's ``closedAt`` projection (#9727)
        so churn windows keyed on close time behave identically under the
        fake and the real port.
        """
        self._maybe_rate_limit()
        rows = [
            {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body,
                "updated_at": getattr(issue, "updated_at", "2026-01-01T00:00:00Z"),
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
            pr_pipeline = next(
                (lbl for lbl in pr.labels if lbl.startswith("hydraflow-")),
                "",
            )
            issue_pipeline = next(
                (lbl for lbl in issue.labels if lbl.startswith("hydraflow-")),
                "",
            )
            commits = pr.commits

            kind: str | None = None
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
                    issue_label=issue_pipeline,
                    pr_label=pr_pipeline,
                    kind=kind,  # type: ignore[arg-type]
                    detected_at=datetime.now(UTC),
                )
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
        return f"[#{issue_number}] {issue_title}"

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

    async def create_rc_branch(self, rc_branch: str) -> str:
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
        return []

    async def delete_branch(self, branch: str) -> bool:
        _ = branch
        return True

    async def list_recent_promotion_prs(self, days: int = 7) -> list[dict[str, Any]]:
        _ = days
        return []

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
            if sub == "close":
                # Best-effort: extract issue number from positional args.
                for a in args[2:]:
                    if a.isdigit():
                        await self.close_issue(int(a))
                        break
                return ""
            if sub == "view":
                return _json.dumps({"comments": []})

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

        # Unknown verb: return empty JSON array — safe default for
        # callers that ``json.loads`` the output.
        return "[]"
