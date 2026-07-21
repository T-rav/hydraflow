"""Regression pin for issue #9768 (slices 1–5) — cassette-cluster pins.

Issue #9768 is the canonical ``fake_coverage_auditor`` rollup for the
FakeGitHub adapter surface. The first carved slice (subsuming #9436) closes
the **staging/RC promotion cluster** — the 13 methods StagingPromotionLoop
(ADR-0042) drives in production. Slice 2 closes the **issue-lifecycle /
label cluster** — 11 methods covering issue dedup, state/staleness reads,
comment/label listing, and the label-mutation trio (``remove_label`` /
``transition`` / ``swap_pipeline_labels``) plus ``find_label_drift``
(ADR-0088). Slice 3 closes the **PR review / label-mutation cluster** — 11
methods covering PR comment/review submission (``post_pr_comment`` /
``submit_review``), review/check/approval reads (``get_pr_approvers`` /
``get_pr_checks`` / ``get_pr_reviews`` / ``get_pr_mergeable``), PR label
mutation (``add_pr_labels`` / ``remove_pr_label``), and PR lifecycle/title
(``close_pr`` / ``update_pr_title`` / ``expected_pr_title``). Slice 4 closes
the **PR/label read & query cluster** — 11 methods covering open-PR lookup
(``find_open_pr_for_branch``), PR listings (``list_prs_by_label`` /
``list_open_prs`` / ``list_all_open_prs`` / ``list_conflicting_prs``), HITL
listing (``list_hitl_items``), label-count aggregation (``get_label_counts``),
and PR content reads (``get_pr_diff`` / ``get_pr_diff_names`` /
``get_pr_head_sha`` / ``get_pr_recent_commit_diffs``). Slice 5 — the FINAL
slice — closes the **workflow-run / CI-log / git-op / alerts cluster**: the
last 12 methods covering workflow-run reads (``list_workflow_runs`` /
``list_runs_for_workflow`` / ``get_workflow_run_jobs`` /
``count_workflow_run_artifacts``), security-alert reads
(``fetch_code_scanning_alerts`` / ``get_dependabot_alerts``), CI-log reads
(``fetch_ci_failure_logs``), and git/branch ops (``push_branch`` /
``branch_has_diff_from_main`` / ``pull_main`` /
``refresh_pr_branch_with_arch_regen`` / ``upload_screenshot``). With slice 5
the FakeGitHub adapter surface is fully cassetted and
``GRANDFATHERED_UNCASSETTED["FakeGitHub"]`` is empty. Each pin uses
the auditor's *own* catalog functions so it fails for exactly the reason the
auditor would re-file:

* Deleting one of the cluster's cassettes (or renaming its
  ``input.command``, the key the auditor matches on — the filename is
  irrelevant) reopens the gap.
* Neither pin asserts the full surface is covered — the rollup still
  tracks the remaining uncovered methods. Each only ratchets its own slice
  shut.

NOTE (auditor call-signature footgun): ``catalog_fake_methods`` must be
called with ``repo_root=`` for FakeGitHub — without it the scaffolding
filter (real-surface intersection against PRManager ∪ PRPort) does not
apply and builder/seed helpers pollute the surface. Each pin also asserts
its slice's methods are classified adapter-surface, so a future
reclassification (e.g. into ``_FAKE_HELPER_OVERRIDES``) is a loud, reviewed
change rather than silent coverage-accounting drift.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import (
    _FAKE_TO_CASSETTE_DIR,
    catalog_cassette_methods,
    catalog_fake_methods,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAKE_DIR = _REPO_ROOT / "src" / "mockworld" / "fakes"
_CASSETTE_ROOT = _REPO_ROOT / "tests" / "trust" / "contracts" / "cassettes"

# The #9768 slice-1 cluster: everything StagingPromotionLoop calls to cut,
# CI-gate, merge, and garbage-collect an RC promotion (ADR-0042).
_PROMOTION_CLUSTER = frozenset(
    {
        "apply_staging_branch_protection",
        "create_promotion_pr",
        "create_rc_branch",
        "delete_branch",
        "ensure_branch_exists",
        "find_open_promotion_pr",
        "list_rc_branches",
        "list_recent_promotion_prs",
        "merge_promotion_pr",
        "push_synthetic_commit",
        "update_pr_base",
        "update_pr_branch",
        "wait_for_ci",
    }
)


def test_issue_9768_promotion_cluster_is_cassetted() -> None:
    """Every promotion-cluster method stays covered by a github cassette."""
    catalog = catalog_fake_methods(_FAKE_DIR, repo_root=_REPO_ROOT)
    assert "FakeGitHub" in catalog, "FakeGitHub not found in fakes catalog"

    surface = set(catalog["FakeGitHub"]["adapter-surface"])
    misclassified = sorted(_PROMOTION_CLUSTER - surface)
    assert misclassified == [], (
        "promotion-cluster methods no longer classified adapter-surface "
        f"(auditor accounting drift?): {misclassified}"
    )

    cassette_dir = _CASSETTE_ROOT / _FAKE_TO_CASSETTE_DIR["FakeGitHub"]
    cassetted = catalog_cassette_methods(cassette_dir)
    uncovered = sorted(_PROMOTION_CLUSTER - cassetted)
    assert uncovered == [], (
        "promotion-cluster methods lost cassette coverage under "
        f"{cassette_dir.relative_to(_REPO_ROOT)}/ (input.command is the "
        f"coverage key, not the filename): {uncovered}"
    )


# The #9768 slice-2 cluster: issue de-dup, state/staleness reads,
# comment/label listing, and the three label-mutation primitives
# (remove_label / transition / swap_pipeline_labels) plus find_label_drift
# (ADR-0088).
_ISSUE_LIFECYCLE_CLUSTER = frozenset(
    {
        "find_existing_issue",
        "find_label_drift",
        "get_issue_state",
        "get_issue_updated_at",
        "list_closed_issues_by_label",
        "list_issue_comments",
        "list_open_issue_numbers",
        "remove_label",
        "swap_pipeline_labels",
        "transition",
        "update_issue_body",
    }
)


def test_issue_9768_issue_lifecycle_cluster_is_cassetted() -> None:
    """Every issue-lifecycle-cluster method stays covered by a github cassette."""
    catalog = catalog_fake_methods(_FAKE_DIR, repo_root=_REPO_ROOT)
    assert "FakeGitHub" in catalog, "FakeGitHub not found in fakes catalog"

    surface = set(catalog["FakeGitHub"]["adapter-surface"])
    misclassified = sorted(_ISSUE_LIFECYCLE_CLUSTER - surface)
    assert misclassified == [], (
        "issue-lifecycle-cluster methods no longer classified adapter-surface "
        f"(auditor accounting drift?): {misclassified}"
    )

    cassette_dir = _CASSETTE_ROOT / _FAKE_TO_CASSETTE_DIR["FakeGitHub"]
    cassetted = catalog_cassette_methods(cassette_dir)
    uncovered = sorted(_ISSUE_LIFECYCLE_CLUSTER - cassetted)
    assert uncovered == [], (
        "issue-lifecycle-cluster methods lost cassette coverage under "
        f"{cassette_dir.relative_to(_REPO_ROOT)}/ (input.command is the "
        f"coverage key, not the filename): {uncovered}"
    )


# The #9768 slice-3 cluster: PR comment/review submission, review/check/
# approval reads, PR label mutation, and PR lifecycle/title methods.
_PR_REVIEW_CLUSTER = frozenset(
    {
        "add_pr_labels",
        "close_pr",
        "expected_pr_title",
        "get_pr_approvers",
        "get_pr_checks",
        "get_pr_mergeable",
        "get_pr_reviews",
        "post_pr_comment",
        "remove_pr_label",
        "submit_review",
        "update_pr_title",
    }
)


def test_issue_9768_pr_review_cluster_is_cassetted() -> None:
    """Every PR-review-cluster method stays covered by a github cassette."""
    catalog = catalog_fake_methods(_FAKE_DIR, repo_root=_REPO_ROOT)
    assert "FakeGitHub" in catalog, "FakeGitHub not found in fakes catalog"

    surface = set(catalog["FakeGitHub"]["adapter-surface"])
    misclassified = sorted(_PR_REVIEW_CLUSTER - surface)
    assert misclassified == [], (
        "PR-review-cluster methods no longer classified adapter-surface "
        f"(auditor accounting drift?): {misclassified}"
    )

    cassette_dir = _CASSETTE_ROOT / _FAKE_TO_CASSETTE_DIR["FakeGitHub"]
    cassetted = catalog_cassette_methods(cassette_dir)
    uncovered = sorted(_PR_REVIEW_CLUSTER - cassetted)
    assert uncovered == [], (
        "PR-review-cluster methods lost cassette coverage under "
        f"{cassette_dir.relative_to(_REPO_ROOT)}/ (input.command is the "
        f"coverage key, not the filename): {uncovered}"
    )


# The #9768 slice-4 cluster: open-PR lookup, PR listings (label-filtered,
# unfiltered, conflicting), HITL listing, label-count aggregation, and PR
# content reads (diff / diff-names / head-sha / recent-commit-diffs).
_PR_READ_QUERY_CLUSTER = frozenset(
    {
        "find_open_pr_for_branch",
        "get_label_counts",
        "get_pr_diff",
        "get_pr_diff_names",
        "get_pr_head_sha",
        "get_pr_recent_commit_diffs",
        "list_all_open_prs",
        "list_conflicting_prs",
        "list_hitl_items",
        "list_open_prs",
        "list_prs_by_label",
    }
)


def test_issue_9768_pr_read_query_cluster_is_cassetted() -> None:
    """Every PR/label read-&-query-cluster method stays covered by a cassette."""
    catalog = catalog_fake_methods(_FAKE_DIR, repo_root=_REPO_ROOT)
    assert "FakeGitHub" in catalog, "FakeGitHub not found in fakes catalog"

    surface = set(catalog["FakeGitHub"]["adapter-surface"])
    misclassified = sorted(_PR_READ_QUERY_CLUSTER - surface)
    assert misclassified == [], (
        "PR-read-query-cluster methods no longer classified adapter-surface "
        f"(auditor accounting drift?): {misclassified}"
    )

    cassette_dir = _CASSETTE_ROOT / _FAKE_TO_CASSETTE_DIR["FakeGitHub"]
    cassetted = catalog_cassette_methods(cassette_dir)
    uncovered = sorted(_PR_READ_QUERY_CLUSTER - cassetted)
    assert uncovered == [], (
        "PR-read-query-cluster methods lost cassette coverage under "
        f"{cassette_dir.relative_to(_REPO_ROOT)}/ (input.command is the "
        f"coverage key, not the filename): {uncovered}"
    )


# The #9768 slice-5 cluster (FINAL): workflow-run reads, security-alert reads,
# CI-log reads, and git/branch ops. Closing this empties
# GRANDFATHERED_UNCASSETTED["FakeGitHub"] — the whole adapter surface is
# cassetted.
_WORKFLOW_GITOP_CLUSTER = frozenset(
    {
        "branch_has_diff_from_main",
        "count_workflow_run_artifacts",
        "fetch_ci_failure_logs",
        "fetch_code_scanning_alerts",
        "get_dependabot_alerts",
        "get_workflow_run_jobs",
        "list_runs_for_workflow",
        "list_workflow_runs",
        "pull_main",
        "push_branch",
        "refresh_pr_branch_with_arch_regen",
        "upload_screenshot",
    }
)


def test_issue_9768_workflow_gitop_cluster_is_cassetted() -> None:
    """Every workflow-run/CI-log/git-op/alerts method stays covered by a cassette."""
    catalog = catalog_fake_methods(_FAKE_DIR, repo_root=_REPO_ROOT)
    assert "FakeGitHub" in catalog, "FakeGitHub not found in fakes catalog"

    surface = set(catalog["FakeGitHub"]["adapter-surface"])
    misclassified = sorted(_WORKFLOW_GITOP_CLUSTER - surface)
    assert misclassified == [], (
        "Workflow-gitop-cluster methods no longer classified adapter-surface "
        f"(auditor accounting drift?): {misclassified}"
    )

    cassette_dir = _CASSETTE_ROOT / _FAKE_TO_CASSETTE_DIR["FakeGitHub"]
    cassetted = catalog_cassette_methods(cassette_dir)
    uncovered = sorted(_WORKFLOW_GITOP_CLUSTER - cassetted)
    assert uncovered == [], (
        "Workflow-gitop-cluster methods lost cassette coverage under "
        f"{cassette_dir.relative_to(_REPO_ROOT)}/ (input.command is the "
        f"coverage key, not the filename): {uncovered}"
    )


def test_issue_9768_fakegithub_surface_fully_cassetted() -> None:
    """The whole point of #9768: FakeGitHub has zero uncovered surface methods.

    Slice 5 is the closing slice. This end-state pin fails loudly if any
    future adapter-surface method lands without a cassette — the gap must
    never silently reopen now that the rollup is closed.
    """
    catalog = catalog_fake_methods(_FAKE_DIR, repo_root=_REPO_ROOT)
    surface = set(catalog["FakeGitHub"]["adapter-surface"])
    cassette_dir = _CASSETTE_ROOT / _FAKE_TO_CASSETTE_DIR["FakeGitHub"]
    cassetted = catalog_cassette_methods(cassette_dir)
    uncovered = sorted(surface - cassetted)
    assert uncovered == [], (
        "FakeGitHub adapter surface regressed to a non-zero coverage gap "
        f"(#9768 was closed at zero): {uncovered}. Record a cassette + "
        "dispatcher branch for each."
    )
