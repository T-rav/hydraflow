"""Regression tests for issue #3040: inline imports must not shadow module-level bindings.

Scans source files for function-body imports that re-import a name already
available at module level.  This catches the pattern where a developer adds
``from foo import bar`` inside a function body even though ``bar`` is already
imported at the top of the file.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

# Files that were fixed in issue #3040.  If new inline-shadow violations are
# introduced they will be caught by the parametrised test below.
_FIXED_FILES = [
    "events.py",
    "dashboard_routes/_routes.py",
    "pr_manager.py",
    "acceptance_criteria.py",
]


def _is_type_checking_guard(node: ast.If) -> bool:
    """Return True if the ``if`` node is ``if TYPE_CHECKING:``."""
    test = node.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return bool(isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


def _module_level_names(tree: ast.Module) -> set[str]:
    """Return names imported at module level, excluding TYPE_CHECKING blocks.

    Imports guarded by ``if TYPE_CHECKING:`` are only available during static
    analysis — runtime re-imports of those names inside function bodies are
    legitimate and should not be flagged.
    """
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.If) and not _is_type_checking_guard(node):
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    for alias in child.names:
                        names.add(alias.asname or alias.name)
    return names


def _inline_shadow_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Find function-body imports that shadow a module-level name.

    Returns a list of ``(line_number, imported_name)`` pairs.
    """
    top_names = _module_level_names(tree)
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    name = alias.asname or alias.name
                    if name in top_names:
                        violations.append((child.lineno, name))
    return violations


@pytest.mark.parametrize("rel_path", _FIXED_FILES)
def test_no_inline_shadow_imports(rel_path: str) -> None:
    """Files fixed in #3040 must not regress with new inline shadow imports."""
    path = SRC_DIR / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} not found")
    tree = ast.parse(path.read_text())
    violations = _inline_shadow_imports(tree)
    if violations:
        detail = "\n".join(f"  line {line}: {name}" for line, name in violations)
        msg = textwrap.dedent(f"""\
            {rel_path} has inline imports that shadow module-level bindings:
            {detail}
            Move these to module level or remove the duplicates.""")
        pytest.fail(msg)


class TestAppendJsonlModuleLevelImport:
    """Verify events.py uses append_jsonl from the module-level import."""

    def test_append_jsonl_in_module_namespace(self) -> None:
        """append_jsonl should be importable from events' module scope."""
        import events

        assert hasattr(events, "append_jsonl"), (
            "events.py should import append_jsonl at module level"
        )

    def test_append_sync_calls_append_jsonl(self, tmp_path: Path) -> None:
        """EventLog._append_sync should successfully call append_jsonl."""
        from events import EventLog

        log_path = tmp_path / "test.jsonl"
        event_log = EventLog(log_path)
        event_log._append_sync('{"test": true}')

        assert log_path.exists()
        assert '{"test": true}' in log_path.read_text()
