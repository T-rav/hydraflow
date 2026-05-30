"""Host-side contract tests for sandbox Tier-2 scenarios.

The real sandbox runner imports these modules inside the Playwright container
with a container-only pytest config. These tests keep the scenario modules
honest from the normal host test lane without booting Docker.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from types import ModuleType

import pytest

from mockworld.seed import MockWorldSeed

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "tests" / "sandbox_scenarios" / "scenarios"


def _scenario_module_names() -> list[str]:
    return sorted(
        path.stem for path in SCENARIO_DIR.glob("s*.py") if path.name != "__init__.py"
    )


def _load(name: str) -> ModuleType:
    return importlib.import_module(f"tests.sandbox_scenarios.scenarios.{name}")


@pytest.mark.parametrize("module_name", _scenario_module_names())
def test_sandbox_scenario_exports_contract(module_name: str) -> None:
    module = _load(module_name)

    assert isinstance(getattr(module, "NAME", None), str)
    assert module_name == module.NAME
    assert isinstance(getattr(module, "DESCRIPTION", None), str)
    assert module.DESCRIPTION.strip()
    assert callable(getattr(module, "seed", None))

    seed = module.seed()
    assert isinstance(seed, MockWorldSeed)
    assert isinstance(seed.to_json(), str)

    if module_name == "s00_smoke":
        assert not hasattr(module, "assert_outcome")
        return

    assert inspect.iscoroutinefunction(getattr(module, "assert_outcome", None))
    params = list(inspect.signature(module.assert_outcome).parameters)
    assert params == ["api", "page"]


@pytest.mark.parametrize("module_name", _scenario_module_names())
def test_sandbox_scenarios_do_not_import_pytest_at_module_scope(
    module_name: str,
) -> None:
    path = SCENARIO_DIR / f"{module_name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name == "pytest" for alias in node.names):
                offenders.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
            offenders.append(node.lineno)

    assert offenders == [], (
        f"{path.relative_to(ROOT)} imports pytest at module scope on line(s) "
        f"{offenders}. Sandbox scenarios are imported in a runtime image that "
        "does not ship pytest; import pytest lazily inside assert_outcome instead."
    )


@pytest.mark.parametrize("module_name", _scenario_module_names())
def test_sandbox_scenarios_do_not_skip_or_xfail(module_name: str) -> None:
    path = SCENARIO_DIR / f"{module_name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr in {"skip", "xfail"}:
            offenders.append(node.lineno)

    assert offenders == [], (
        f"{path.relative_to(ROOT)} calls skip/xfail on line(s) {offenders}. "
        "Sandbox scenarios must either assert a real runtime contract or be "
        "removed from the runnable scenario catalog."
    )


@pytest.mark.parametrize("module_name", _scenario_module_names())
def test_sandbox_scenarios_are_not_placeholders(module_name: str) -> None:
    path = SCENARIO_DIR / f"{module_name}.py"
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    forbidden = [
        marker
        for marker in (
            "known-broken",
            "placeholder pass",
            "soft-pass",
            "tracking issue",
            "tracking:",
        )
        if marker in text
    ]

    assert forbidden == [], (
        f"{path.relative_to(ROOT)} contains placeholder markers {forbidden}. "
        "Sandbox scenarios are merge gates; remove non-working scenarios "
        "instead of keeping ignored green tests."
    )


def test_sandbox_runner_catalog_matches_scenario_files() -> None:
    from tests.sandbox_scenarios.runner.loader import load_all_scenarios

    discovered = {module.NAME for module in load_all_scenarios()}
    expected = set(_scenario_module_names())
    assert discovered == expected


def test_every_tier2_scenario_has_assert_outcome_except_smoke() -> None:
    modules = [_load(name) for name in _scenario_module_names()]
    missing = [
        module.NAME
        for module in modules
        if module.NAME != "s00_smoke"
        and not inspect.iscoroutinefunction(getattr(module, "assert_outcome", None))
    ]

    assert missing == []
