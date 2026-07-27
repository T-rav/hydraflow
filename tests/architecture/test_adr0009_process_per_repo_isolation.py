"""ADR-0009 enforcement: process-per-repo path isolation.

ADR-0009 (Multi-Repo Process-Per-Repo Model) decides that every managed repo
is isolated by scoping its filesystem paths under the repo slug, so a crash or
state file in one repo can never touch another and same-numbered issues in
different repos never collide (Decision §2 environment-driven isolation, §3
repo-scoped workspaces). The load-bearing, machine-checkable part of that
decision is the path-namespacing contract on ``HydraFlowConfig``:

* ``workspace_path_for_issue(n)`` resolves to
  ``<workspace_base>/<repo_slug>/issue-<n>``.
* ``repo_data_root`` resolves to ``<data_root>/<repo_slug>``.

These asserting tests bind that decision to a runnable check so the isolation
guarantee cannot silently regress to a flat (collision-prone) layout.
"""

from __future__ import annotations

from pathlib import Path

import config


def test_workspace_paths_are_repo_slug_scoped_and_collision_free() -> None:
    """ADR-0009 §3: workspace paths are namespaced by repo slug, so the same
    issue number in two different repos resolves to two distinct paths."""
    base = Path("/data/ws")
    alpha = config.HydraFlowConfig(repo="acme/alpha", workspace_base=base)
    beta = config.HydraFlowConfig(repo="acme/beta", workspace_base=base)

    alpha_path = alpha.workspace_path_for_issue(7)
    beta_path = beta.workspace_path_for_issue(7)

    # Each path is exactly <workspace_base>/<repo_slug>/issue-<n>.
    assert alpha_path == base / "acme-alpha" / "issue-7"
    assert beta_path == base / "acme-beta" / "issue-7"
    # The repo slug is a real path segment (not folded into the leaf name).
    assert alpha_path.parent.name == alpha.repo_slug == "acme-alpha"
    assert beta_path.parent.name == beta.repo_slug == "acme-beta"
    # The isolation invariant: same issue number, different repos -> no clash.
    assert alpha_path != beta_path


def test_repo_data_root_is_scoped_under_the_repo_slug() -> None:
    """ADR-0009 §2: per-repo state lives under ``<data_root>/<repo_slug>``, so
    state files, event logs, and session logs are isolated per repo."""
    root = Path("/data/state")
    cfg = config.HydraFlowConfig(repo="acme/alpha", data_root=root)

    assert cfg.repo_data_root == root / "acme-alpha"
    assert cfg.repo_data_root.parent == root
