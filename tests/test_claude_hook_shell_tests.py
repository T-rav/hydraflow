"""Bridge: run every `tests/hooks/*.sh` shell test in the default suite.

#11125: `tests/hooks/test_auto_lint_strip_warning.sh` was a real regression
test that no Makefile target or workflow ever invoked — it could rot or fail
silently forever. This bridge discovers ALL `tests/hooks/*.sh` scripts (so a
newly added shell test is wired automatically) and runs each under bash,
requiring exit 0. Shell tests print "PASS" on success by convention.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK_TESTS = sorted((REPO_ROOT / "tests" / "hooks").glob("*.sh"))


def test_shell_test_discovery_is_nonempty() -> None:
    # If the directory is ever emptied/moved, fail loud instead of silently
    # collecting zero parametrized cases (the exact rot #11125 describes).
    assert _HOOK_TESTS, "expected shell tests under tests/hooks/"


@pytest.mark.parametrize("script", _HOOK_TESTS, ids=lambda p: p.name)
def test_hook_shell_test_passes(script: Path) -> None:
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"{script.name} failed (rc={result.returncode})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
