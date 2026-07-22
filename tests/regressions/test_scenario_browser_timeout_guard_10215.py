"""Regression #10215: bound make scenario-browser's blast radius on a hang.

test_start_button_starts_orchestrator hung for ~2715s with zero pytest output,
force-cancelled only by the CI job's 45-minute timeout-minutes ceiling (the
test's own 10s Playwright waits never fired — the shared event loop itself
was blocked). Root cause deferred to #10253; this pins the immediate
mitigation: `make scenario-browser` must run under a per-test pytest-timeout
guard well below the 45-minute job ceiling, so a future hang fails loudly in
under two minutes instead of burning the full CI budget.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
MAKEFILE = REPO_ROOT / "Makefile"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Generous margin above the suite's real waits (max explicit Playwright
# wait in tests/scenarios/browser/ is 10s) but far below the CI job's
# 45-minute timeout-minutes ceiling, so a hang fails fast without flaking
# on ordinary CI slowness.
_MAX_ALLOWED_TIMEOUT_S = 300


def _scenario_browser_recipe() -> str:
    text = MAKEFILE.read_text()
    start = text.index("\nscenario-browser:")
    end = text.index("\n\n", start)
    return text[start:end]


def test_scenario_browser_pytest_invocation_has_timeout_guard() -> None:
    recipe = _scenario_browser_recipe()
    pytest_line = next(
        ln for ln in recipe.splitlines() if "pytest tests/scenarios/browser/" in ln
    )
    match = re.search(r"--timeout=(\d+)", pytest_line)
    assert match is not None, (
        "make scenario-browser must pass --timeout=N to pytest (#10215) — "
        "without it, a hung test consumes the full 45-minute job budget "
        "instead of failing loudly in seconds"
    )
    assert 0 < int(match.group(1)) <= _MAX_ALLOWED_TIMEOUT_S, (
        "make scenario-browser's pytest --timeout must stay well below the "
        "45-minute CI job ceiling to actually bound the blast radius (#10215)"
    )


def test_pytest_timeout_declared_as_test_dependency() -> None:
    data = tomllib.loads(PYPROJECT.read_text())
    test_deps = data["project"]["optional-dependencies"]["test"]
    assert any(dep.startswith("pytest-timeout") for dep in test_deps), (
        "pytest-timeout must be declared under [project.optional-dependencies] "
        "test — make scenario-browser's --timeout flag (#10215) is a no-op "
        "without the plugin installed"
    )
