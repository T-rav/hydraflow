"""Regression test for issue #6739.

Bug: report_issue_loop.py contained a hardcoded "hydraflow-plan" fallback
string that bypassed the config's planner_label setting.  When planner_label
is empty (e.g. misconfiguration), the site silently reverted to the hardcoded
default rather than using the config-provided value or raising.

Expected behaviour after fix:
  - No inline "hydraflow-plan" string literals in report_issue_loop.py — all
    label access goes through the config object.

(The sibling Sentry-ingest case was retired when Sentry.io was removed.)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"


# ---------------------------------------------------------------------------
# Source-level: no hardcoded "hydraflow-plan" string literals
# ---------------------------------------------------------------------------


def _collect_string_literals(filepath: Path) -> list[str]:
    """Return all string-literal values in *filepath* via AST walking."""
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    return literals


class TestNoHardcodedPlanLabel:
    """Issue #6739 — no inline 'hydraflow-plan' string constant in loop files."""

    def test_report_issue_loop_has_no_hardcoded_plan_label(self) -> None:
        """report_issue_loop.py must not contain a 'hydraflow-plan' string literal."""
        literals = _collect_string_literals(SRC_DIR / "report_issue_loop.py")
        assert "hydraflow-plan" not in literals, (
            "report_issue_loop.py still contains a hardcoded 'hydraflow-plan' "
            "string literal — the fallback should come from config, not "
            "an inline constant"
        )
