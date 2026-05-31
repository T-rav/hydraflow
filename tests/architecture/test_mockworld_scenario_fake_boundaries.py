"""Guard MockWorld scenarios against bypassing stateful fake adapters."""

from __future__ import annotations

import ast
from pathlib import Path

SCENARIO_ROOT = Path("tests/scenarios")
WATCHED_GITHUB_METHODS = {
    "add_labels",
    "add_pr_labels",
    "close_issue",
    "create_issue",
    "post_comment",
    "post_pr_comment",
    "remove_label",
    "swap_pipeline_labels",
    "update_issue_body",
}
MOCK_CONSTRUCTORS = {"AsyncMock", "MagicMock", "Mock"}


def _is_mockworld_scenario(tree: ast.AST, source: str) -> bool:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.endswith("fakes.mock_world")
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name.endswith("fakes.mock_world") for alias in node.names
        ):
            return True
    return "MockWorld(" in source or "run_with_loops(" in source


def _mock_constructor_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _find_raw_github_side_effect_mocks(path: Path) -> list[str]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    if not _is_mockworld_scenario(tree, source):
        return []

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue

        constructor = _mock_constructor_name(node.value)
        if constructor not in MOCK_CONSTRUCTORS:
            continue

        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr in WATCHED_GITHUB_METHODS
            ):
                if _is_documented_pattern_b(node, parents):
                    continue
                violations.append(
                    f"{path}:{node.lineno} assigns {target.attr} to {constructor}"
                )

    return violations


def _is_documented_pattern_b(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            doc = ast.get_docstring(current) or ""
            if "Pattern B" in doc or "direct instantiation" in doc:
                return True
        current = parents.get(current)
    return False


def test_mockworld_scenarios_assert_github_side_effects_through_fake_state() -> None:
    """MockWorld scenarios must use FakeGitHub for stateful GitHub side effects."""
    violations: list[str] = []
    for path in sorted(SCENARIO_ROOT.rglob("test*.py")):
        violations.extend(_find_raw_github_side_effect_mocks(path))

    assert violations == []
