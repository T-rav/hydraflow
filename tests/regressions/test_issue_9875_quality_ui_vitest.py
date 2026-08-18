"""Regression guard for issue #9875: `make quality` must plan the UI vitest stage.

CI's "Dashboard Build" job runs the src/ui vitest suite (``npm test`` ->
``src/ui/scripts/run-vitest.cjs``), but ``make quality`` historically did not,
so a stale UI test (a ``Header.test.jsx`` asserting an old rendered arrow
count) passed every local gate and only went red at the PR check — the
``mergeStateStatus=UNSTABLE`` merge behind #9617. The merge-state gate is the
symptom backstop; this pin guards the prevention:

- ``make -n quality`` must include the UI vitest stage, run through the same
  entry point CI uses (``run-vitest.cjs`` — not raw ``npx vitest``, which
  skips the wrapper's jsdom patch and encoding shim);
- node is an optional local tool, so the stage must degrade loudly-but-green
  when node or an installed ``src/ui/node_modules`` is missing AND src/ui is
  untouched (skip with a visible warning). Since #11090 the skip is
  conditional: a node-less machine whose checkout CHANGED src/ui fails loud
  instead — see tests/regressions/test_ui_skip_false_green_11090.py;
- the gating command must not be piped to ``tail`` — pipes mask the exit code
  (the known ``make | tail`` footgun);
- ``quality-lite`` (the pre-push gate) deliberately stays vitest-free so
  pre-push stays fast.

Asserted against ``make -n`` output — the real execution plan, after variable
expansion — rather than raw Makefile text, so a refactor of the recipe wiring
cannot silently drop the stage while a text pin still matches. ``make -n``
executes nothing here: the quality chain intentionally contains no ``$(MAKE)``
recipe lines (those run even under ``-n``).
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@cache
def _dry_run_plan(target: str) -> str:
    """Return the `make -n <target>` execution plan from the repo root."""
    # Strip inherited make state: when this test itself runs under `make
    # quality`, MAKEFLAGS/MFLAGS would otherwise leak into the child make.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}
    }
    proc = subprocess.run(  # noqa: S603 — fixed argv, repo-root cwd
        ["make", "-n", target],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, (
        f"`make -n {target}` failed (rc={proc.returncode}):\n{proc.stderr}"
    )
    return proc.stdout


def test_quality_plan_includes_ui_vitest_stage() -> None:
    plan = _dry_run_plan("quality")

    assert "run-vitest.cjs" in plan, (
        "make quality no longer plans the UI vitest stage — src/ui changes "
        "would pass local quality while CI's Dashboard Build goes red "
        "(issue #9875)"
    )


def test_ui_stage_uses_ci_entry_point() -> None:
    # CI runs `npm test` -> `node ./scripts/run-vitest.cjs run`. Parity means
    # the same wrapper (it patches vitest's jsdom chunk and injects the
    # encoding shim); raw `npx vitest run` can fail where CI passes.
    plan = _dry_run_plan("quality")

    assert "node ./scripts/run-vitest.cjs run" in plan


def test_ui_stage_degrades_loudly_but_green_without_node() -> None:
    plan = _dry_run_plan("quality")

    assert "command -v node" in plan, (
        "the UI vitest stage must guard on node availability so quality "
        "stays green (but warns) on machines without node"
    )
    assert "src/ui/node_modules" in plan, (
        "the UI vitest stage must guard on an installed src/ui/node_modules "
        "(npm ci) so quality stays green (but warns) on fresh clones"
    )
    assert "[ui-tests SKIPPED]" in plan, (
        "the skip branch must warn visibly — silent skips hide the parity gap"
    )


def test_ui_stage_exit_code_is_not_masked_by_tail_pipe() -> None:
    plan = _dry_run_plan("quality")

    offending = [
        line
        for line in plan.splitlines()
        if "run-vitest.cjs" in line and "| tail" in line
    ]
    assert offending == [], (
        "the UI vitest command must not be piped to tail — the pipe masks "
        f"the exit code (known make-quality footgun): {offending}"
    )


def test_quality_lite_plan_stays_vitest_free() -> None:
    # Deliberate: quality-lite is the pre-push gate and must stay fast.
    # See the comment above the quality-lite target in the Makefile.
    plan = _dry_run_plan("quality-lite")

    assert "run-vitest.cjs" not in plan


def test_standalone_test_ui_target_runs_same_stage() -> None:
    plan = _dry_run_plan("test-ui")

    assert "node ./scripts/run-vitest.cjs run" in plan
    assert "[ui-tests SKIPPED]" in plan


def test_dry_run_quality_does_not_block_on_a_held_host_lock(
    tmp_path: Path,
) -> None:
    """`make -n quality` must never reach the #11219 host lock at all.

    `quality`'s recipe wraps `$(MAKE) quality-unlocked` in
    scripts/quality_host_lock.py (#11219). GNU Make force-executes any
    recipe line containing the literal text "$(MAKE)" even under `-n`
    (dry-run) — that's the mechanism a nested `make -n` relies on to show
    the recursive plan (see the assertions above). Left unguarded, that
    means a plain `make -n quality` doesn't just print: it really invokes
    the lock wrapper, which does a real ``fcntl.flock``. On a host already
    running a real `make quality` — this exact test file, invoked as
    PART OF a real `make quality` run, is that host — the dry run would
    block waiting for a lock the outer real run is still holding, up to
    ``HYDRAFLOW_QUALITY_LOCK_TIMEOUT`` (3600s default): a self-deadlock.

    Simulates that contention directly: hold the lock the way an outer
    real run would, then assert `make -n quality` still finishes fast
    instead of queueing behind it.
    """
    lock_path = tmp_path / "hydraflow-quality.lock"
    handle = lock_path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}
        }
        env["TMPDIR"] = str(tmp_path) + os.sep

        proc = subprocess.run(  # noqa: S603 — fixed argv, repo-root cwd
            ["make", "-n", "quality"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert proc.returncode == 0, (
            f"`make -n quality` failed while a host lock was held "
            f"(rc={proc.returncode}):\n{proc.stderr}"
        )
        assert "run-vitest.cjs" in proc.stdout, (
            "the dry-run plan should still show the full nested "
            "quality-unlocked plan even though the lock wrapper itself "
            "was bypassed"
        )
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
