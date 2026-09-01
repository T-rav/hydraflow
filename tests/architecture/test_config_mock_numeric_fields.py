"""No test may stand in for HydraFlowConfig with a bare MagicMock (#11827).

A bare ``MagicMock()`` answers every attribute with a Mock, including the 326
numeric fields production code compares against — and comparison against a Mock
RAISES (``1 > MagicMock()`` is a ``TypeError``, in both operand orders). The
mock is harmless only for as long as no test *reaches* the comparison, so a
green fixture is not evidence that it is safe, only that nothing got there yet.

That is what makes this a latent crash rather than a wrong branch, and why it
recurred: each fix named the one field that had just bitten, and the next field
was always unnamed. Three fixtures broke this way on 2026-08-30 and three more
on 2026-08-31 — the second three from adding two ordinary config knobs.

``tests.helpers.config_mock()`` seeds every numeric field from
``HydraFlowConfig.model_fields``, so a knob added tomorrow is covered without
editing anything. This guard is the half that stops a new bare one appearing.

The detector is deliberately shape-based, not name-based: "a Mock that gets two
or more REAL config-field attributes set on it" is what a config stand-in IS,
whatever the variable is called.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

from config import HydraFlowConfig  # noqa: E402

_FIELDS = frozenset(HydraFlowConfig.model_fields)
#: Two real config attributes is the floor. One could be a coincidence — plenty
#: of unrelated mocks carry a ``.repo`` or a ``.model``; two together is a
#: config stand-in.
_MIN_CONFIG_ATTRS = 2


def _bare_mock_names(tree: ast.Module) -> set[str]:
    """Names assigned a no-argument ``MagicMock()`` / ``Mock()``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        called = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else ""
        )
        if called in {"MagicMock", "Mock"} and not node.value.args:
            if node.value.keywords:
                continue  # spec=/return_value= etc. is a deliberate stand-in
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def config_shaped_mocks(source: str) -> dict[str, set[str]]:
    """``{variable: real config fields set on it}`` for each config stand-in."""
    tree = ast.parse(source)
    bare = _bare_mock_names(tree)
    hits: dict[str, set[str]] = defaultdict(set)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in bare
                and target.attr in _FIELDS
            ):
                hits[target.value.id].add(target.attr)
    return {v: f for v, f in hits.items() if len(f) >= _MIN_CONFIG_ATTRS}


def test_the_detector_sees_a_config_shaped_mock() -> None:
    """Positive control: with zero offenders left, the sweep below would be
    vacuous unless the detector is shown to still fire."""
    found = config_shaped_mocks(
        "from unittest.mock import MagicMock\n"
        "config = MagicMock()\n"
        "config.gh_max_retries = 3\n"
        "config.repo_root = '/tmp'\n"
    )
    assert found == {"config": {"gh_max_retries", "repo_root"}}


def test_the_detector_ignores_an_ordinary_mock() -> None:
    """Negative control: a Mock that is not standing in for a config is fine."""
    assert (
        config_shaped_mocks(
            "from unittest.mock import MagicMock\n"
            "prs = MagicMock()\n"
            "prs.list_all_open_prs.return_value = []\n"
        )
        == {}
    )


def test_no_test_stands_in_for_config_with_a_bare_mock() -> None:
    offenders: list[str] = []
    for path in sorted((_ROOT / "tests").rglob("*.py")):
        try:
            found = config_shaped_mocks(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        offenders.extend(
            f"{path.relative_to(_ROOT)}:{var} (sets {len(fields)} config fields)"
            for var, fields in sorted(found.items())
        )

    assert not offenders, (
        "These tests stand in for HydraFlowConfig with a bare MagicMock, so "
        "every numeric field they do not set answers with a Mock — and "
        "production comparing against one RAISES the moment a code path "
        "reaches it:\n  "
        + "\n  ".join(offenders)
        + "\nUse tests.helpers.config_mock(), which seeds every numeric field "
        "from HydraFlowConfig.model_fields so a knob added later is covered "
        "without editing the fixture."
    )
