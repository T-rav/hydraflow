"""Module-level constants, records and errors of the ``fake_github`` package.

Split out of the original ``src/mockworld/fakes/fake_github.py`` (god-class
decomposition, Refs #11547) so every mixin module has a cycle-free home for the
shared module-level surface: the in-memory records the fake stores
(``FakeIssue`` / ``FakePR`` / ``FakeComment``), the two errors it raises, and the
label / naming / quiet-shape constants its methods read. Everything here is
re-exported from ``fake_github/__init__.py`` for back-compat — external callers
continue to do ``from mockworld.fakes.fake_github import X``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
