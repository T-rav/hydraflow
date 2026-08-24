"""Regression test for issue #6438.

Bug: places in source use ``if not self._x`` to guard Optional-typed
attributes instead of ``if self._x is None``.  The falsy form can
short-circuit on a non-None but falsy value — most dangerously on
``unittest.mock.Mock(spec=...)`` objects that implement ``__bool__``.

Locations:
  - ``src/pr_unsticker.py:480`` — ``if not self._hitl_runner:``

Convention: ``docs/wiki/gotchas.md`` — "Falsy checks on optional
objects".
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_falsy_guards(filepath: Path, attr_names: set[str]) -> list[tuple[int, str]]:
    """Return ``(lineno, attr)`` for ``if not self.<attr>:`` guard patterns.

    Matches ``If`` nodes whose test is ``UnaryOp(Not, Attribute(Name('self'), attr))``
    where *attr* is one of the given names.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # Match: ``not self.<attr>``
        if (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Attribute)
            and isinstance(test.operand.value, ast.Name)
            and test.operand.value.id == "self"
            and test.operand.attr in attr_names
        ):
            violations.append((node.lineno, test.operand.attr))
    return violations


# ---------------------------------------------------------------------------
# AST tests — detect the bad pattern in each cited file
# ---------------------------------------------------------------------------

_KNOWN_VIOLATIONS = [
    # ``pr_unsticker`` became a package (#11547 batch 7); the
    # ``self._hitl_runner`` guard this pins lives in the resolve slice.
    ("pr_unsticker/_resolve.py", {"_hitl_runner"}),
]


class TestFalsyGuardsOnOptionalAttributes:
    """``if not self._x`` on Optional-typed attrs must be ``if self._x is None``."""

    @pytest.mark.parametrize(
        ("filename", "attrs"),
        _KNOWN_VIOLATIONS,
        ids=[f[0] for f in _KNOWN_VIOLATIONS],
    )
    def test_no_falsy_guard_on_optional_attr(
        self, filename: str, attrs: set[str]
    ) -> None:
        filepath = SRC_ROOT / filename
        assert filepath.exists(), f"{filename} does not exist"
        # Guard the guard: a file that never mentions the attribute yields no
        # violations for the same reason a fixed file does. After a
        # decomposition that is exactly how a roster entry pointed at the wrong
        # slice reads as green (#11673).
        source = filepath.read_text()
        absent = sorted(a for a in attrs if a not in source)
        assert not absent, (
            f"{filename} never mentions {absent} — the pin moved off the code "
            "it guards; find the slice that owns the attribute."
        )

        violations = _find_falsy_guards(filepath, attrs)
        assert violations == [], (
            f"{filename} uses 'if not self.<attr>' instead of 'is None' "
            f"(violates avoided-patterns.md): {violations}"
        )
