"""Regression pins for the two sharpest bugs fixed during #9724 (PR #10006).

1. The git-apply ``-p1`` prefix-differential bypass: a patch section headed
   ``--- x/<path>`` / ``+++ y/<path>`` applies cleanly under ``-p1`` while
   contributing zero targets to the tripwire's path scan. The fix is the
   git-native changed-set assertion (``_assert_only_module_changed``), which
   must reject any worktree whose actual touched set is not exactly the
   target builder module.

2. The lifetime-cumulative trend bug: ``compute_skill_efficiency`` diffed two
   cumulative telemetry snapshots as if they were per-window data, so a
   genuine 100x cost regression on a high-volume source computed a ~9.9%
   trend and never crossed ``INEFFICIENCY_THRESHOLD``. The fix derives
   marginal-window cost-per-call from snapshot deltas.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from prompt_efficiency import INEFFICIENCY_THRESHOLD, compute_skill_efficiency
from skill_prompt_eval_loop import _assert_only_module_changed

_MODULE_REL = "src/diff_sanity.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(cwd),
        },
    )


@pytest.fixture()
def stub_worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / "tests" / "trust").mkdir(parents=True)
    (wt / _MODULE_REL).write_text("x = 1\n")
    (wt / "tests" / "trust" / "harness.py").write_text("real = True\n")
    _git(wt, "init", "-q")
    _git(wt, "add", ".")
    _git(wt, "commit", "-qm", "seed")
    return wt


async def test_prefix_differential_harness_rewrite_is_rejected(
    stub_worktree: Path,
) -> None:
    """#9724 pin 1: a bundled non-a/b-prefixed section that rewrites the
    validation harness must be caught by the changed-set assertion even
    though the tripwire's a/b path scan cannot see it."""
    (stub_worktree / _MODULE_REL).write_text("x = 2\n")
    (stub_worktree / "tests" / "trust" / "harness.py").write_text("real = False\n")
    with pytest.raises(RuntimeError, match="unexpected"):
        await _assert_only_module_changed(stub_worktree, _MODULE_REL)


async def test_builder_only_change_passes(stub_worktree: Path) -> None:
    (stub_worktree / _MODULE_REL).write_text("x = 3\n")
    await _assert_only_module_changed(stub_worktree, _MODULE_REL)


def test_hundredx_regression_on_high_volume_source_fires() -> None:
    """#9724 pin 2: 100 new calls at $1.00 on a source with 100k lifetime
    calls at $0.01 must trend ~99x, not ~9.9% (the cumulative-snapshot bug)."""
    baseline = {
        "diff-sanity": {
            "inference_calls": 100_000,
            "estimated_cost_microusd": 1_000_000_000,
            "usage_unavailable_calls": 0,
        }
    }
    current = {
        "diff-sanity": {
            "inference_calls": 100_100,
            "estimated_cost_microusd": 1_100_000_000,
            "usage_unavailable_calls": 0,
        }
    }
    rows = compute_skill_efficiency(current, baseline)
    assert rows[0].trend_vs_baseline is not None
    assert rows[0].trend_vs_baseline > INEFFICIENCY_THRESHOLD
    assert rows[0].trend_vs_baseline == pytest.approx(99.0, rel=0.01)
