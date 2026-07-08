from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def test_orchestrator_registers_fitness_scorecard() -> None:
    text = (SRC / "orchestrator.py").read_text()
    assert '"fitness_scorecard": svc.fitness_scorecard_loop' in text
    assert '("fitness_scorecard", self._svc.fitness_scorecard_loop.run)' in text
    assert ".set_loops(" in text  # loops wired into the producer


def test_service_registry_has_field() -> None:
    text = (SRC / "service_registry.py").read_text()
    assert "fitness_scorecard_loop" in text
    # Field is declared in the ServiceRegistry dataclass.
    tree = ast.parse(text)
    found = any(
        isinstance(node, ast.ClassDef)
        and node.name == "ServiceRegistry"
        and any(
            isinstance(stmt, ast.AnnAssign)
            and getattr(stmt.target, "id", None) == "fitness_scorecard_loop"
            for stmt in node.body
        )
        for node in ast.walk(tree)
    )
    assert found, "fitness_scorecard_loop must be a ServiceRegistry field"
