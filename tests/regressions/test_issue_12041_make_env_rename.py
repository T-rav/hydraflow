"""Regression #12041: `make env` read as dotenv setup; the real dotenv
seeder is `make setup`. The dep-heal target is renamed `deps-heal` and `env`
survives only as a deprecated alias that delegates — this pins all three
facts so the alias cannot be dropped silently while callers remain, and the
new name cannot lose the heal body.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAKEFILE = (_REPO_ROOT / "Makefile").read_text()
_LAUNCHER = (_REPO_ROOT / "scripts" / "run-factory-isolated.sh").read_text()


def _target_body(name: str) -> str:
    match = re.search(rf"^{name}:\n((?:\t.*\n)+)", _MAKEFILE, re.M)
    assert match, f"Makefile target {name!r} not found"
    return match.group(1)


def test_deps_heal_carries_the_heal_body() -> None:
    body = _target_body("deps-heal")
    assert "uv sync --all-extras" in body
    assert "import pytest" in body  # the sanity check survived the rename


def test_env_is_a_deprecated_delegating_alias() -> None:
    body = _target_body("env")
    assert "deps-heal" in body, "alias must delegate to the new name"
    assert "deprecated" in body.lower()
    assert "make setup" in body, "the alias must point dotenv seekers at setup"
    assert "uv sync" not in body, "alias delegates; it must not duplicate the body"


def test_factory_launcher_calls_the_new_name() -> None:
    assert re.search(r"^make deps-heal$", _LAUNCHER, re.M)
    assert not re.search(r"^make env$", _LAUNCHER, re.M), (
        "the launcher must not depend on the deprecated alias"
    )
