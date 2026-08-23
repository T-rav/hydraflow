"""Back-compat re-exports for the ``fake_github`` package.

The original ``src/mockworld/fakes/fake_github.py`` (2176 lines / a 1656-LOC,
133-method ``FakeGitHub``) was split into this package for mass discipline
(Refs #11547). All existing imports keep working::

    from mockworld.fakes.fake_github import FakeGitHub      # still works
    from mockworld.fakes.fake_github import FakeIssue, FakePR, RateLimitError

Layout — one module per GitHub surface, each mirroring the ``pr_manager_*``
mixin it doubles so the fake and the real adapter read alike:

  * ``_common.py``     — ``FakeIssue`` / ``FakePR`` / ``FakeComment``, the two
    errors, and the module-level label / naming / quiet-shape constants.
  * ``_fake.py``       — the ``FakeGitHub`` class: its state, ``from_seed``, and
    the core mutations ``PRManager`` itself keeps in its class body.
  * ``_seeding.py``    — scenario seeding + rate-limit fault injection
    (scaffolding: no real-adapter counterpart).
  * ``_issues.py``     — ``pr_manager_issues``
  * ``_labels.py``     — ``pr_manager_labels``
  * ``_comments.py``   — ``pr_manager_comments``
  * ``_pr_queries.py`` — ``pr_manager_pr_queries``
  * ``_branches.py``   — ``pr_manager_branches``
  * ``_ci.py``         — ``pr_manager_ci``
  * ``_dashboard.py``  — ``pr_manager_dashboard``
  * ``_drift.py``      — ``pr_manager_drift``
  * ``_promotion.py``  — ``pr_manager_promotion``
  * ``_artifacts.py``  — ``pr_manager_artifacts``
  * ``_gh_cli.py``     — the raw ``gh`` argv seam (``PRManager._run_gh``)

Each slice is a mixin ``FakeGitHub`` inherits, so there is exactly ONE class
identity: every Port seam, cassette dispatcher and scenario harness resolves to
the same object it did before.
"""

from __future__ import annotations

from ._common import (
    _DISPATCHABLE_STAGE_LABELS,
    _GIT_OID_RE,
    _QUIET_UNKNOWN_GH_SHAPES,
    _RC_BRANCH_PREFIX,
    _RC_FIXED_DATE,
    FakeComment,
    FakeGitHubUnmodelledCommand,
    FakeIssue,
    FakePR,
    RateLimitError,
)
from ._fake import FakeGitHub

__all__ = [
    "FakeComment",
    "FakeGitHub",
    "FakeGitHubUnmodelledCommand",
    "FakeIssue",
    "FakePR",
    "RateLimitError",
    "_DISPATCHABLE_STAGE_LABELS",
    "_GIT_OID_RE",
    "_QUIET_UNKNOWN_GH_SHAPES",
    "_RC_BRANCH_PREFIX",
    "_RC_FIXED_DATE",
]
