"""Regression: factory self-operation gaps closed in PR #10143.

Two gaps forced manual operator toil in the 2026-07-21 session and must not
silently reopen:

1. The class-5 human-branch shepherd (``DependabotMergeLoop``, #9889)
   auto-merges CI-green human/agent work branches, but its prefix set omitted
   ``perf/``/``ci/``/``build/`` — a batch of green ``perf/`` CI-speedup PRs
   had NO merge path and were hand-merged one at a time. Pin the three
   Conventional-Commit prefixes into the allowlist.

2. ``.gitattributes`` maps ``docs/arch/.meta.json`` to ``merge=arch-meta``
   (#10099) but the driver is registered only by ``make ensure-hooks``, which
   never runs during factory worktree setup. ``WorkspaceManager._install_hooks``
   must register the driver itself — in BOTH host and docker modes — or the
   mapping is inert and every agent worktree re-conflicts on the regen stamp.
   Pin that the registration exists, uses the ensure-hooks driver command, and
   is wired into ``_install_hooks``.
"""

from __future__ import annotations

import inspect

from dependabot_merge_loop import _HUMAN_SHEPHERD_BRANCH_PREFIXES
from workspace import WorkspaceManager


def test_shepherd_allowlist_covers_perf_ci_build() -> None:
    for prefix in ("perf/", "ci/", "build/"):
        assert prefix in _HUMAN_SHEPHERD_BRANCH_PREFIXES, (
            f"{prefix} dropped from the shepherd allowlist — green {prefix} PRs "
            "would again have no auto-merge path (PR #10143)"
        )


def test_install_hooks_registers_arch_meta_driver() -> None:
    # The registration helper exists and mirrors `make ensure-hooks` exactly.
    driver_src = inspect.getsource(WorkspaceManager._register_arch_meta_merge_driver)
    assert "merge.arch-meta.driver" in driver_src
    assert "cp -- %B %A" in driver_src

    # …and _install_hooks actually calls it, so the driver reaches the worktree
    # regardless of host vs docker mode. Without this wiring the .meta.json
    # merge=arch-meta mapping is inert in factory worktrees.
    install_src = inspect.getsource(WorkspaceManager._install_hooks)
    assert "_register_arch_meta_merge_driver" in install_src
