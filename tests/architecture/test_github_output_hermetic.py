"""GITHUB_OUTPUT hermeticity guard (#11562).

CLI scripts under ``scripts/`` default their ``--github-output``/``--out``
argument to ``os.environ.get("GITHUB_OUTPUT")`` so the Actions workflow can
omit the flag. Two invariants keep that from leaking into the test suite:

1. **Session scrub.** ``tests/conftest.py::setup_test_environment`` removes
   ``GITHUB_OUTPUT`` from the process environment for the whole session, so an
   in-process ``main()`` call can never see the runner's real step-output file
   (the #11560 env-dependent red: verdict went to the file on CI, to stdout on
   a laptop). Pinned here both textually and live — on a runner this test is
   the canary that the scrub is still in force.
2. **Call-time reads.** Every ``GITHUB_OUTPUT`` environment read in
   ``scripts/`` and ``src/`` must sit inside a function body (resolved when
   ``main()`` runs, under the scrub), never at module level (frozen at import,
   before any fixture can intervene).
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFTEST = REPO_ROOT / "tests" / "conftest.py"
_SCAN_ROOTS = ("scripts", "src")
_SKIP_PARTS = frozenset({"node_modules", "ui"})

# The load-bearing real sites (anti-vacuity canary): a broken scanner cannot
# pass the call-time assertion vacuously on an empty roster.
_KNOWN_SITES = frozenset(
    {
        "scripts/classify_smoke_log.py",
        "scripts/staging_rc_dryrun_pin.py",
        "scripts/staging_rc_dryrun_report.py",
    }
)


@dataclass(frozen=True)
class EnvRead:
    path: str
    lineno: int
    enclosing: str | None  # None == module level (import time)


def _is_os_module(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "os"


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and _is_os_module(node.value)
    ) or (isinstance(node, ast.Name) and node.id == "environ")


def _first_arg_is_github_output(node: ast.Call) -> bool:
    return bool(
        node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "GITHUB_OUTPUT"
    )


class _Scanner(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.reads: list[EnvRead] = []
        self._stack: list[str] = []

    def _record(self, node: ast.AST) -> None:
        enclosing = "::".join(self._stack) if self._stack else None
        self.reads.append(EnvRead(self.path, node.lineno, enclosing))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Parameter defaults and decorators evaluate when the ``def`` statement
        # runs — import time for a top-level function — NOT per call, so they
        # belong to the OUTER scope. Only the body is call-time.
        for child in (
            *node.args.defaults,
            *node.args.kw_defaults,
            *node.decorator_list,
        ):
            if child is not None:
                self.visit(child)
        self._stack.append(node.name)
        for stmt in node.body:
            self.visit(stmt)
        self._stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if _first_arg_is_github_output(node) and (
            # os.environ.get(...) / environ.get(...)
            (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and _is_os_environ(func.value)
            )
            # os.getenv(...)
            or (
                isinstance(func, ast.Attribute)
                and func.attr == "getenv"
                and _is_os_module(func.value)
            )
            # getenv(...) after ``from os import getenv``
            or (isinstance(func, ast.Name) and func.id == "getenv")
        ):
            self._record(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if (
            _is_os_environ(node.value)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "GITHUB_OUTPUT"
        ):
            self._record(node)
        self.generic_visit(node)


def scan_source(source: str, path: str) -> list[EnvRead]:
    scanner = _Scanner(path)
    scanner.visit(ast.parse(source, filename=path))
    return scanner.reads


def scan_repo() -> list[EnvRead]:
    reads: list[EnvRead] = []
    for root in _SCAN_ROOTS:
        for file in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = file.relative_to(REPO_ROOT)
            if _SKIP_PARTS & set(rel.parts):
                continue
            reads.extend(scan_source(file.read_text(encoding="utf-8"), str(rel)))
    return reads


def test_scanner_flags_a_module_level_read() -> None:
    source = dedent(
        """
        import os
        DEFAULT = os.environ.get("GITHUB_OUTPUT")
        """
    )
    assert scan_source(source, "scripts/x.py") == [EnvRead("scripts/x.py", 3, None)]


def test_scanner_attributes_call_time_reads_to_their_function() -> None:
    source = dedent(
        """
        import os

        def main(argv=None):
            a = os.environ.get("GITHUB_OUTPUT")
            b = os.getenv("GITHUB_OUTPUT")
            c = os.environ["GITHUB_OUTPUT"]
            return a, b, c
        """
    )
    reads = scan_source(source, "scripts/x.py")
    assert [r.lineno for r in reads] == [5, 6, 7]
    assert {r.enclosing for r in reads} == {"main"}


def test_scanner_treats_parameter_defaults_as_import_time() -> None:
    """``def main(out=os.environ.get(...))`` evaluates at def time, not per call."""
    source = dedent(
        """
        import os

        def main(out=os.environ.get("GITHUB_OUTPUT")):
            return out
        """
    )
    assert scan_source(source, "scripts/x.py") == [EnvRead("scripts/x.py", 4, None)]


def test_scanner_sees_bare_name_imports() -> None:
    source = dedent(
        """
        from os import environ, getenv

        def main():
            a = environ.get("GITHUB_OUTPUT")
            b = getenv("GITHUB_OUTPUT")
            c = environ["GITHUB_OUTPUT"]
            return a, b, c
        """
    )
    reads = scan_source(source, "scripts/x.py")
    assert [r.lineno for r in reads] == [5, 6, 7]
    assert {r.enclosing for r in reads} == {"main"}


def test_scanner_ignores_other_env_keys() -> None:
    source = 'import os\nX = os.environ.get("GITHUB_SHA")\n'
    assert scan_source(source, "scripts/x.py") == []


def test_every_github_output_read_is_call_time() -> None:
    reads = scan_repo()
    found = {r.path for r in reads}
    assert found >= _KNOWN_SITES, (
        f"scanner lost known GITHUB_OUTPUT sites: {sorted(_KNOWN_SITES - found)}"
    )
    import_time = [r for r in reads if r.enclosing is None]
    assert not import_time, (
        "GITHUB_OUTPUT read at import time (frozen before the session scrub "
        "can run) — move it inside main() (#11562): "
        + ", ".join(f"{r.path}:{r.lineno}" for r in import_time)
    )


def test_session_scrub_declares_github_output() -> None:
    tree = ast.parse(_CONFTEST.read_text(encoding="utf-8"), filename=str(_CONFTEST))
    fixture = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "setup_test_environment"
        ),
        None,
    )
    assert fixture is not None, "tests/conftest.py lost setup_test_environment"
    literals = {
        node.value
        for node in ast.walk(fixture)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "GITHUB_OUTPUT" in literals, (
        "setup_test_environment no longer scrubs GITHUB_OUTPUT — in-process CLI "
        "main() calls would inherit the runner's step-output file again (#11562)"
    )


def test_github_output_is_absent_while_tests_run() -> None:
    assert "GITHUB_OUTPUT" not in os.environ, (
        "GITHUB_OUTPUT is visible to a running test — the session scrub in "
        "tests/conftest.py::setup_test_environment is not in force (#11562)"
    )
