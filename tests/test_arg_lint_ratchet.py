"""Ratchet guard for the ruff ARG (flake8-unused-arguments) rule.

Locks in the config change that enabled ARG for production code while
exempting tests, whose mock/fixture/callback signatures legitimately carry
unused params. If someone drops ``ARG`` from the ruff ``select`` list or
removes the ``tests/**`` exemption, these fail loudly. Src-level cleanliness
is enforced separately by CI's repo-wide ``ruff check .``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _ruff_lint_config() -> dict:
    data = tomllib.loads(_PYPROJECT.read_text())
    return data["tool"]["ruff"]["lint"]


def test_arg_rule_is_selected() -> None:
    assert "ARG" in _ruff_lint_config()["select"]


def test_tests_tree_is_exempt_from_arg() -> None:
    per_file = _ruff_lint_config()["per-file-ignores"]
    assert "ARG" in per_file.get("tests/**", []), (
        "tests/** must ignore ARG — mock/fixture/callback signatures "
        "legitimately carry unused params"
    )
