"""Regression pin for #11136 — `.claude/` surfaces in impacted-test selection.

`_hard_full_suite_reason` forced the full suite for `.githooks/**` but had no
rule for `.claude/**`, so edits to Claude hooks or `.claude/settings.json`
(tool-gating, secret scanning, pre-commit validation) selected only the
always-on floor. The behavioral surfaces now force the full suite; the prose
assets (`agents/`, `skills/`, `commands/`) are a DELIBERATE non-mapping.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Same by-path load idiom as tests/test_impacted_tests.py — scripts/ is not
# an importable package from the tests root.
_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "impacted_tests.py"
_spec = importlib.util.spec_from_file_location("impacted_tests", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
impacted_tests = importlib.util.module_from_spec(_spec)
sys.modules["impacted_tests"] = impacted_tests
_spec.loader.exec_module(impacted_tests)


def test_claude_hooks_and_settings_force_full_suite() -> None:
    for path in (".claude/hooks/hf.block-destructive-git.sh", ".claude/settings.json"):
        reason = impacted_tests._hard_full_suite_reason(path, path.rsplit("/", 1)[-1])
        assert reason is not None and "full suite" in reason, path


def test_claude_prose_assets_do_not_force_full_suite() -> None:
    for path in (".claude/agents/reviewer.md", ".claude/skills/deploy/SKILL.md"):
        reason = impacted_tests._hard_full_suite_reason(path, path.rsplit("/", 1)[-1])
        assert reason is None, path
