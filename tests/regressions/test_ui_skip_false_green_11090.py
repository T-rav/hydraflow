"""Regression pins for the UI-vitest false-green skip (#11090, #11113).

A fresh worktree has no ``src/ui/node_modules``, so `make quality`'s UI lane
printed ``[ui-tests SKIPPED]`` and exited 0 even when the branch CHANGED
src/ui — a false green that repeatedly merged untested React changes during
the operator-console work. And on machines where node is installed only via
nvm, ``command -v node`` fails in make's non-interactive shell, forcing the
same skip path even with deps installed (#11113).

The fix lives in the Makefile's ``UI_TEST_CMD``: the skip is now conditional
(src/ui untouched vs origin/staging), UI-touching checkouts FAIL loudly, and
node discovery falls back to the newest nvm-installed binary. These pins
lock the shape of that shell block — behavioral tests of a Makefile recipe
would need node fixtures; text pins follow the established pattern of
`tests/regressions/test_issue_10883.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _ui_test_cmd_block() -> str:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^UI_TEST_CMD = .*?(?:\n\n|\ntest-ui:)", text, re.S | re.M)
    assert match, "UI_TEST_CMD block not found in Makefile"
    return match.group(0)


def test_ui_lane_fails_loud_when_src_ui_touched() -> None:
    block = _ui_test_cmd_block()
    assert "[ui-tests FAILED]" in block, (
        "UI_TEST_CMD lost its fail branch — a missing-deps run on a "
        "UI-touching checkout would silently skip again (#11090)"
    )
    assert "exit 1" in block
    assert "merge-base HEAD origin/staging" in block, (
        "the fail branch must key on whether src/ui differs from "
        "origin/staging, not fail unconditionally"
    )


def test_ui_lane_keeps_the_benign_skip_path() -> None:
    # Python-only worktrees without node must still pass quality: the
    # SKIPPED warning path is load-bearing, only its reachability narrowed.
    assert "[ui-tests SKIPPED]" in _ui_test_cmd_block()


def test_ui_lane_discovers_nvm_node() -> None:
    block = _ui_test_cmd_block()
    assert ".nvm/versions/node" in block, (
        "UI_TEST_CMD lost the nvm fallback — machines with node only via "
        "nvm silently skip the UI suite in make's non-login shell (#11113)"
    )
