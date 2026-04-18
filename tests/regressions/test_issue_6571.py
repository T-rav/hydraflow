"""Regression test for issue #6571.

``CodeGroomingSettings`` exposes ``min_priority`` (P0–P3) and ``enabled_audits``
(list of audit names) — both settable via the dashboard.  However,
``CodeGroomingLoop._do_work()`` never reads either field:

* Severity filtering uses the hardcoded ``_ACTIONABLE_SEVERITIES`` frozenset
  (``{"critical", "high"}``) instead of deriving thresholds from
  ``min_priority``.
* The audit skill is always ``/hf.audit-code`` regardless of
  ``enabled_audits``.

These tests will fail (RED) until the loop consumes the settings it advertises.
"""

from __future__ import annotations

import pytest

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


# ---------------------------------------------------------------------------
# Test 1 — min_priority is never referenced by the grooming loop
# ---------------------------------------------------------------------------


class TestMinPriorityConsumed:
    """``min_priority`` must influence the severity filter in _do_work."""

    @pytest.mark.xfail(reason="Regression for issue #6571 — fix not yet landed", strict=False)
    def test_code_grooming_loop_references_min_priority(self) -> None:
        """The loop source must read ``min_priority`` somewhere.

        Fails until ``CodeGroomingLoop`` actually uses the setting
        instead of the hardcoded ``_ACTIONABLE_SEVERITIES`` frozenset.
        """
        source = (SRC / "code_grooming_loop.py").read_text()
        assert "min_priority" in source, (
            "code_grooming_loop.py never references 'min_priority' — "
            "the CodeGroomingSettings field is settable but has no runtime effect "
            "(issue #6571)"
        )


# ---------------------------------------------------------------------------
# Test 2 — enabled_audits is never referenced by the grooming loop
# ---------------------------------------------------------------------------


class TestEnabledAuditsConsumed:
    """``enabled_audits`` must influence which audits are run."""

    @pytest.mark.xfail(reason="Regression for issue #6571 — fix not yet landed", strict=False)
    def test_code_grooming_loop_references_enabled_audits(self) -> None:
        """The loop source must read ``enabled_audits`` somewhere.

        Fails until ``CodeGroomingLoop`` selects or filters audits based
        on the operator-supplied list instead of always running
        ``/hf.audit-code``.
        """
        source = (SRC / "code_grooming_loop.py").read_text()
        assert "enabled_audits" in source, (
            "code_grooming_loop.py never references 'enabled_audits' — "
            "the CodeGroomingSettings field is settable but has no runtime effect "
            "(issue #6571)"
        )


# ---------------------------------------------------------------------------
# Test 3 — _ACTIONABLE_SEVERITIES is hardcoded, not derived from settings
# ---------------------------------------------------------------------------


class TestSeverityFilterNotHardcoded:
    """The severity filter must be derived from config, not a module-level constant."""

    @pytest.mark.xfail(reason="Regression for issue #6571 — fix not yet landed", strict=False)
    def test_actionable_severities_not_hardcoded_frozenset(self) -> None:
        """Verify the loop does not use a hardcoded frozenset for severity filtering.

        ``_ACTIONABLE_SEVERITIES = frozenset({"critical", "high"})`` at module
        level means no operator configuration can change the threshold.  This
        test fails until the filtering logic reads ``min_priority`` from
        ``CodeGroomingSettings``.
        """
        source = (SRC / "code_grooming_loop.py").read_text()
        tree = ast.parse(source)

        # Look for a module-level assignment of _ACTIONABLE_SEVERITIES
        hardcoded_severity_constant = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_ACTIONABLE_SEVERITIES"
                for t in node.targets
            ):
                hardcoded_severity_constant = True
                break

        assert not hardcoded_severity_constant, (
            "_ACTIONABLE_SEVERITIES is a hardcoded module-level constant in "
            "code_grooming_loop.py — severity filtering should be derived from "
            "CodeGroomingSettings.min_priority, not a frozenset literal "
            "(issue #6571)"
        )
