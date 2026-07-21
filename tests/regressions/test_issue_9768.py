"""Regression pin for issue #9768 (slice 1) — promotion-cluster cassettes.

Issue #9768 is the canonical ``fake_coverage_auditor`` rollup for the
FakeGitHub adapter surface. The first carved slice (subsuming #9436) closes
the **staging/RC promotion cluster** — the 13 methods StagingPromotionLoop
(ADR-0042) drives in production. This pin uses the auditor's *own* catalog
functions so it fails for exactly the reason the auditor would re-file:

* Deleting one of the 13 cassettes (or renaming its ``input.command``, the
  key the auditor matches on — the filename is irrelevant) reopens the gap.
* The pin does NOT assert the full surface is covered — the rollup still
  tracks the remaining uncovered methods. It only ratchets this slice shut.

NOTE (auditor call-signature footgun): ``catalog_fake_methods`` must be
called with ``repo_root=`` for FakeGitHub — without it the scaffolding
filter (real-surface intersection against PRManager ∪ PRPort) does not
apply and builder/seed helpers pollute the surface. The pin also asserts
each slice method is classified adapter-surface, so a future
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
