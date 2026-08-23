"""Scenario-seeding and fault-injection surface of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's
side of ``in-memory scaffolding (no real-adapter counterpart)``, so the fake and the thing it doubles read alike.

One concern: everything a scenario calls to BUILD the world before the pipeline
runs — ``add_*`` / ``seed_*`` / ``set_*`` / ``script_*`` builders, the plain
inspectors (``issue`` / ``pr`` / ``pr_for_issue``), and the rate-limit fault
injection every adapter method consults through ``_maybe_rate_limit``. None of
it has a real-adapter counterpart: the fake-coverage auditor classifies this
whole surface as scaffolding, not un-cassetted adapter surface.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from ._common import FakeComment, FakeIssue, FakePR, RateLimitError

if TYPE_CHECKING:
    from typing import Any

    from models import PRDiffStats


class FakeGitHubSeedingMixin:
    """Scenario-seeding and fault-injection surface of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _alerts: dict[str, list[Any]]
    _arch_refresh_calls: dict[int, int]
    _arch_refresh_outcome: dict[int, bool]
    _branch_commits: dict[str, list[dict[str, str]]]
    _branch_heads: dict[str, str | None]
    _ci_failure_logs: dict[int, str]
    _ci_main_status: tuple[str, str]
    _ci_scripts: dict[int, deque[tuple[bool, str]]]
    _commit_diffs: dict[int, list[str]]
    _default_pr_diff: str | None
    _issues: dict[int, FakeIssue]
    _legacy_protection: dict[str, dict[str, Any]]
    _pr_commit_messages: dict[int, str]
    _pr_diff_names: dict[int, list[str]]
    _pr_diff_stats: dict[int, PRDiffStats]
    _pr_diffs: dict[int, str]
    _prs: dict[int, FakePR]
    _rate_limit_remaining: int | None
    _rate_limit_reset_in: int
    _rate_limit_secondary: bool
    _rulesets: dict[str, dict[str, Any]]
    _workflow_artifacts: dict[int, int]
    _workflow_jobs: dict[int, list[dict[str, Any]]]
    _workflow_runs: list[dict[str, Any]]

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

    def set_pr_diff_stats(self, pr_number: int, stats: PRDiffStats) -> None:
        """Seed the diff stats one PR reports (#10788 timeline scenarios)."""
        self._pr_diff_stats[pr_number] = stats.copy()

    def set_pr_diff_names(self, pr_number: int, names: list[str]) -> None:
        """Seed the changed-file list one PR reports (#9974 blame scenarios)."""
        self._pr_diff_names[pr_number] = list(names)

    def set_pr_commit_messages(self, pr_number: int, message: str) -> None:
        """Seed the concatenated commit messages get_pr_commit_messages returns.

        Carries the Skip-Regression: trailer and Closes #N references the
        close-verification controller (#10358) reads.
        """
        self._pr_commit_messages[pr_number] = message

    def seed_ci_failure_log(self, pr_number: int, log: str) -> None:
        """Seed the CI failure log text returned by fetch_ci_failure_logs."""
        self._ci_failure_logs[pr_number] = log

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
