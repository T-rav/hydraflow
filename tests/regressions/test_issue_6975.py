"""Regression test for issue #6975.

Convention drift: StateData.route_back_counts (added in 22083a3c) is missing
from test_state_persistence.py's
``test_state_data_initializes_with_empty_collections_and_zero_counters``.

This test mirrors that defaults assertion and explicitly checks
``route_back_counts``.  It will FAIL (via the completeness guard) until the
canonical test in test_state_persistence.py is updated to include the field.
"""

from __future__ import annotations

import pytest

import ast
from pathlib import Path

from models import StateData

# ---------------------------------------------------------------------------
# Direct default assertion (demonstrates the field *does* default correctly)
# ---------------------------------------------------------------------------


class TestRouteBackCountsDefault:
    """StateData.route_back_counts should default to an empty dict."""

    def test_route_back_counts_defaults_to_empty_dict(self) -> None:
        data = StateData()
        assert hasattr(data, "route_back_counts"), (
            "StateData is missing 'route_back_counts' field entirely"
        )
        assert data.route_back_counts == {}, (
            f"Expected empty dict, got {data.route_back_counts!r}"
        )


# ---------------------------------------------------------------------------
# Completeness guard — the actual convention-drift detection
# ---------------------------------------------------------------------------


class TestDefaultsTestCompleteness:
    """The canonical defaults test must assert every dict/list field on StateData."""

    @pytest.mark.xfail(reason="Regression for issue #6975 — fix not yet landed", strict=False)
    def test_route_back_counts_asserted_in_canonical_defaults_test(self) -> None:
        """Fail until test_state_persistence.py checks route_back_counts."""
        test_file = Path(__file__).resolve().parent.parent / "test_state_persistence.py"
        source = test_file.read_text()

        # Parse the AST to find the exact test method body.
        tree = ast.parse(source)
        target_method = (
            "test_state_data_initializes_with_empty_collections_and_zero_counters"
        )

        found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == target_method:
                    found = True
                    # Get the source lines for this function.
                    method_source = ast.get_source_segment(source, node)
                    assert method_source is not None, (
                        f"Could not extract source for {target_method}"
                    )
                    assert "route_back_counts" in method_source, (
                        f"{target_method} does not assert "
                        f"'data.route_back_counts == {{}}'. "
                        f"See issue #6975: convention drift."
                    )
                    break

        assert found, f"Could not find method {target_method!r} in {test_file}"
