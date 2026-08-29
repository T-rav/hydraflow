"""Synthetic fixture — a pydantic attribute typo pyright MUST report (#11707).

This module is deliberately wrong: ``definitely_not_a_field`` does not exist on
``CanaryModel``. Under a correctly-resolved environment pyright flags it
(``reportAttributeAccessIssue``). When pyright cannot see the project's
site-packages, ``pydantic.BaseModel`` degrades to ``Unknown``, every class
derived from it loses attribute checking, and the error simply *disappears* —
with ``reportMissingImports = false`` suppressing the one diagnostic that would
have announced why. That silent disappearance is what
``tests/regressions/test_issue_11707_pyright_dependency_blindness.py`` watches for.

``tests`` is in ``[tool.pyright].exclude``, so this file's deliberate error
never reaches ``make typecheck`` or CI's Type Check job. The canary re-includes
it through a config derived from ``pyproject.toml``.

Nothing imports this module at runtime; it exists to be type-checked.
"""

from typing import reveal_type

from pydantic import BaseModel

# Positive control. Resolves to `type[BaseModel]` when site-packages is visible
# and to `Unknown` when it is not — the canary asserts on the difference, which
# names the cause instead of only reporting a missing error.
reveal_type(BaseModel)


class CanaryModel(BaseModel):
    """A pydantic model with exactly one real field."""

    real_field: int = 0


def read_a_field_that_does_not_exist() -> int:
    """Access an attribute that does not exist. Pyright must flag this line."""
    model = CanaryModel()
    return model.definitely_not_a_field
