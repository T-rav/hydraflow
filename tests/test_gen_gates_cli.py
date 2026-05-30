"""End-to-end tests for the gen_gates CLI (run as a module from repo root)."""

import subprocess
import sys
from pathlib import Path

MAIN_RULESET = Path("docs/standards/branch_protection/main_ruleset.json")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.gen_gates", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_passes_on_committed_tree() -> None:
    result = _run("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_write_is_idempotent() -> None:
    _run()
    before = MAIN_RULESET.read_text()
    _run()
    after = MAIN_RULESET.read_text()
    assert before == after
