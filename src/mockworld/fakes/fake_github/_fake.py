"""The ``FakeGitHub`` spine.

What stays here is the fake's own state (one ``__init__`` owning every
in-memory store), the ``from_seed`` constructor, and the small core of issue /
PR *mutations* that ``pr_manager.PRManager`` itself keeps in its class body —
``transition``, the task verbs, ``push_branch``, ``create_pr``, ``merge_pr``,
``close_pr`` and the PR-title pair. Every other slice lives in a sibling mixin
module (Refs #11547), each mirroring one ``pr_manager_*`` surface, and is part
of this class by inheritance so the public surface is unchanged.

External callers continue to import via
``from mockworld.fakes.fake_github import FakeGitHub`` — see ``__init__.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mockworld.fakes._factories import PRInfoFactory
from pr_manager import PRManager

# One cohesive slice of ``FakeGitHub`` per module, each extracted verbatim and
# mixed back in by inheritance so the public surface is unchanged — every moved
# method still resolves as an attribute of ``FakeGitHub`` and every Port seam
# resolves to the same object. Each mirrors the ``pr_manager_*`` surface it
# doubles (Refs #11547).
from ._artifacts import FakeGitHubArtifactsMixin
from ._branches import FakeGitHubBranchesMixin
from ._ci import FakeGitHubCIMixin
from ._comments import FakeGitHubCommentsMixin
from ._common import FakePR
from ._dashboard import FakeGitHubDashboardMixin
from ._drift import FakeGitHubDriftMixin
from ._gh_cli import FakeGitHubCliMixin
from ._issues import FakeGitHubIssuesMixin
from ._labels import FakeGitHubLabelsMixin
from ._pr_queries import FakeGitHubPRQueriesMixin
from ._promotion import FakeGitHubPromotionMixin
from ._seeding import FakeGitHubSeedingMixin

if TYPE_CHECKING:
    from collections import deque
    from typing import Any

    from mockworld.seed import MockWorldSeed
    from models import PRDiffStats

    from ._common import FakeIssue


class FakeGitHub(
    FakeGitHubArtifactsMixin,
    FakeGitHubBranchesMixin,
    FakeGitHubCIMixin,
    FakeGitHubCliMixin,
    FakeGitHubCommentsMixin,
    FakeGitHubDashboardMixin,
    FakeGitHubDriftMixin,
    FakeGitHubIssuesMixin,
    FakeGitHubLabelsMixin,
    FakeGitHubPRQueriesMixin,
    FakeGitHubPromotionMixin,
    FakeGitHubSeedingMixin,
):
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

    async def close_pr(self, pr_number: int) -> bool:
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is not None:
            pr.closed = True
        return True

    async def merge_pr(self, pr_number: int, **_kw: Any) -> bool:
        self._maybe_rate_limit()
        if pr_number in self._prs:
            self._prs[pr_number].merged = True
        return True

    @staticmethod
    def expected_pr_title(issue_number: int, issue_title: str) -> str:
        """Return the canonical PR title (``Fixes #N: <title>``, truncated).

        Delegates to the real :meth:`PRManager.expected_pr_title` so the fake
        can never drift from production formatting (#10153). FakeGitHub is cast
        to ``PRPort`` in the sandbox harness, so a divergent title here would be
        live-reachable — a fake that lies about the real format.
        """

        return PRManager.expected_pr_title(issue_number, issue_title)

    async def update_pr_title(self, pr_number: int, title: str) -> bool:
        self._maybe_rate_limit()
        return True
