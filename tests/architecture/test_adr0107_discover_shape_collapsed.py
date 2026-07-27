"""ADR-0107 enforcement: Discover and Shape are collapsed into Plan.

ADR-0107 (Collapse Discover + Shape into Plan) retires Discover and Shape as
standalone pipeline phases: the ``hydraflow-discover`` / ``hydraflow-shape``
labels leave the state machine (amending ADR-0002), the ``DISCOVER`` / ``SHAPE``
``IssueStoreStage`` and ``PipelineStage`` members and their queues are removed,
the ``_discover_loop`` / ``_shape_loop`` supervised loops leave the orchestrator
``loop_factories``, and the ``collapse_discover_shape`` migration flag is
removed. The ``DiscoverRunner`` / ``ShapeRunner`` *engines* survive as
planner-invoked helpers (not stages).

Like ADR-0065, this is a removal decision with a crisp, machine-checkable
surface, so it earns a REAL asserting check. These tests read the on-disk tree
(AST + enum bodies) so the collapsed topology cannot silently regrow a Discover
or Shape stage/label/loop while the retained engines stay put.
"""

from __future__ import annotations

import ast
from pathlib import Path

_DISCOVER_SHAPE = ("DISCOVER", "SHAPE")


def _enum_member_names(path: Path, enum_name: str) -> set[str]:
    """Assigned member names inside the named StrEnum class body."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    members: set[str] = set()
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == enum_name:
            for stmt in cls.body:
                if isinstance(stmt, ast.Assign):
                    members.update(
                        t.id for t in stmt.targets if isinstance(t, ast.Name)
                    )
                elif isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    members.add(stmt.target.id)
    return members


def _string_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


def _defines_class(path: Path, class_name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(n, ast.ClassDef) and n.name == class_name for n in ast.walk(tree)
    )


def test_pipeline_stage_has_no_discover_or_shape(real_repo_root: Path) -> None:
    """ADR-0107: PipelineStage no longer carries DISCOVER / SHAPE members."""
    members = _enum_member_names(real_repo_root / "src" / "models.py", "PipelineStage")
    assert members, "PipelineStage enum not found in models.py"
    leaked = sorted(m for m in _DISCOVER_SHAPE if m in members)
    assert not leaked, f"PipelineStage must not define {leaked} (ADR-0107)"


def test_issue_store_stage_has_no_discover_or_shape(real_repo_root: Path) -> None:
    """ADR-0107: IssueStoreStage no longer carries DISCOVER / SHAPE members."""
    members = _enum_member_names(
        real_repo_root / "src" / "issue_store.py", "IssueStoreStage"
    )
    assert members, "IssueStoreStage enum not found in issue_store.py"
    leaked = sorted(m for m in _DISCOVER_SHAPE if m in members)
    assert not leaked, f"IssueStoreStage must not define {leaked} (ADR-0107)"


def test_discover_shape_labels_removed_from_state_machine(real_repo_root: Path) -> None:
    """ADR-0107 (amends ADR-0002): no live ``hydraflow-discover`` /
    ``hydraflow-shape`` label constants remain in the source tree."""
    offenders: list[str] = []
    src = real_repo_root / "src"
    for path in src.rglob("*.py"):
        try:
            literals = _string_literals(path)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        if "hydraflow-discover" in literals or "hydraflow-shape" in literals:
            offenders.append(path.relative_to(src).as_posix())
    assert not offenders, (
        "hydraflow-discover / hydraflow-shape labels must be removed from the "
        f"state machine (ADR-0107); still referenced in: {sorted(offenders)}"
    )


def test_discover_shape_loops_removed_from_orchestrator(real_repo_root: Path) -> None:
    """ADR-0107 (per ADR-0001): the standalone ``_discover_loop`` /
    ``_shape_loop`` supervised loops are gone from the orchestrator."""
    tree = ast.parse((real_repo_root / "src" / "orchestrator.py").read_text())
    banned = {"_discover_loop", "_shape_loop"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name in banned
        ):
            offenders.append(f"def {node.name}")
        elif isinstance(node, ast.Attribute) and node.attr in banned:
            offenders.append(f"attr {node.attr}")
    assert not offenders, (
        "orchestrator must not define or reference _discover_loop/_shape_loop "
        f"(ADR-0107): {sorted(set(offenders))}"
    )


def test_discover_shape_migration_flag_removed(real_repo_root: Path) -> None:
    """ADR-0107 (Rollout step 3): the ``collapse_discover_shape`` migration
    lever was a temporary flag and is fully removed from config."""
    literals = _string_literals(real_repo_root / "src" / "config.py")
    src = (real_repo_root / "src" / "config.py").read_text()
    assert "collapse_discover_shape" not in src, (
        "the collapse_discover_shape migration flag must be removed (ADR-0107 "
        "rollout step 3 — the flag was a lever, not a permanent mode)"
    )
    assert "HYDRAFLOW_COLLAPSE_DISCOVER_SHAPE" not in literals, (
        "the HYDRAFLOW_COLLAPSE_DISCOVER_SHAPE env override must be removed (ADR-0107)"
    )


def test_discover_shape_runners_survive_as_helpers(real_repo_root: Path) -> None:
    """ADR-0107: the DiscoverRunner / ShapeRunner engines are retained as
    planner-invoked helpers (only the standalone phases were removed)."""
    src = real_repo_root / "src"
    assert _defines_class(src / "discover_runner.py", "DiscoverRunner"), (
        "DiscoverRunner engine must survive as a planner helper (ADR-0107)"
    )
    assert _defines_class(src / "shape_runner.py", "ShapeRunner"), (
        "ShapeRunner engine must survive as a planner helper (ADR-0107)"
    )
