"""Architecture guard: no ``src.``-prefixed imports under ``tests/``.

Because ``src/`` is on ``sys.path``, a module is importable both bare
(``pending_concerns``) and ``src.``-prefixed (``src.pending_concerns``) — but the
two forms resolve to *distinct module objects* (``pending_concerns is
src.pending_concerns`` is ``False``). Production code always imports bare, so a
test that imports the ``src.``-prefixed form silently gets a different object:
autouse ``cache_clear()`` fixtures clear a cache production never touched, and
``patch("src.foo.bar")`` patches a symbol the code under test never sees. The
failure is silent — the fixture or patch simply no-ops — which is worse than a
loud error (see #10874/#10883/#10906).

This guard makes the whole category impossible to reintroduce: no file under
``tests/`` may import a ``src.``-prefixed module. Static AST scan only; it never
imports the offending modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

_IGNORED_DIRS = {".venv", "node_modules", "__pycache__", "hydraflow.egg-info"}


def _is_corpus_fixture(rel: Path) -> bool:
    """Sample-repo corpus data, not HydraFlow's own tests.

    These trees hold snapshots of *other* repositories that HydraFlow analyses
    (the trust adversarial cases and the mock-spec-compliance fixtures). Their
    ``src.``-prefixed imports describe the sample repo's own layout and reference
    modules that do not exist under HydraFlow's ``src/`` (``src.parser``,
    ``src.calc``, ...). They are inert data — never collected or imported by the
    suite — so the dual-module hazard this guard prevents does not apply to them.
    """
    parts = set(rel.parts)
    if "_mock_spec_fixtures" in parts:
        return True
    return "adversarial" in parts and "cases" in parts


def _is_src_prefixed(module: str | None) -> bool:
    return module == "src" or (module or "").startswith("src.")


def test_no_src_prefixed_imports_under_tests(real_repo_root: Path) -> None:
    """Tests import modules bare, never via the ``src.`` alias (#10906)."""
    tests_dir = real_repo_root / "tests"
    offenders: list[str] = []
    for py in tests_dir.rglob("*.py"):
        if _IGNORED_DIRS.intersection(py.parts):
            continue
        rel = py.relative_to(real_repo_root)
        if _is_corpus_fixture(rel):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{rel}:{node.lineno}: import {a.name}"
                    for a in node.names
                    if _is_src_prefixed(a.name)
                ]
            # level > 0 is a relative import (``from . import x``) — never src-prefixed.
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and _is_src_prefixed(node.module)
            ):
                offenders.append(f"{rel}:{node.lineno}: from {node.module} import ...")

    assert offenders == [], (
        "Tests must import modules bare (``from foo import ...``), never via the "
        "``src.`` alias — the two resolve to distinct module objects, so "
        "cache-clear fixtures and patches silently no-op (#10906). Offenders:\n  "
        + "\n  ".join(offenders)
    )
