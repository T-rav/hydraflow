"""Regression: `_flow_stopped` has ONE definition, shared by all three phases.

A concept-scatter sensor (#11792) flagged `_flow_stopped` as independently
introduced in three modules by three separate god-class decompositions
(#11628, #11645, #11658):

    src/implement_phase/_common.py
    src/plan_phase_common.py
    src/review_phase/_flow.py

The parent epic framed the work as "reconciling per-phase drift" and called it
"the semantically-riskier slice". **There was no drift.** All three bodies were
byte-identical — verified by hashing each definition, same md5 three times. So
this is a move, not a semantic merge, and the risk the epic budgeted for did
not exist.

What remains worth guarding is that they do not diverge AGAIN: three copies of
a four-line guard is exactly the shape that drifts silently, because nothing
fails when one copy changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from flows import FLOW_STOP_KEY, flow_stopped

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The phase modules that consume the guard. Derived intent: each of these
#: re-exports the canonical function; none may define its own body again.
PHASE_MODULES = (
    "src/implement_phase/_common.py",
    "src/plan_phase_common.py",
    "src/review_phase/_flow.py",
)


class TestCanonicalBehaviour:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            pytest.param({FLOW_STOP_KEY: True}, True, id="stop_true"),
            pytest.param({FLOW_STOP_KEY: False}, False, id="stop_false"),
            pytest.param({}, False, id="absent"),
            pytest.param({FLOW_STOP_KEY: None}, False, id="stop_none"),
            pytest.param({FLOW_STOP_KEY: "yes"}, True, id="stop_truthy_string"),
            pytest.param({"other": True}, False, id="unrelated_key"),
        ],
    )
    def test_the_guard_reads_only_the_stop_key(
        self, state: dict[str, object], expected: bool
    ) -> None:
        assert flow_stopped(state) is expected


class TestSingleDefinition:
    def test_every_phase_module_binds_the_canonical_function(self) -> None:
        """Identity, not equality — a re-copied body would compare equal in
        behaviour while being a fourth place to change."""
        import implement_phase._common as implement
        import plan_phase_common as plan
        import review_phase._flow as review

        for module in (implement, plan, review):
            assert module._flow_stopped is flow_stopped, (
                f"{module.__name__} no longer binds the canonical guard — a "
                "local copy has come back (#11803)"
            )

    @pytest.mark.parametrize("relative", PHASE_MODULES)
    def test_no_phase_module_redefines_the_guard(self, relative: str) -> None:
        """AST, not grep: a `def _flow_stopped` inside a class or an `if` block
        still shadows the import, and a substring search for the name matches
        the re-export line too."""
        tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))

        definitions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name in {"_flow_stopped", "flow_stopped"}
        ]
        assert not definitions, (
            f"{relative} defines the guard again at line "
            f"{definitions[0].lineno}; it must import the canonical one"
        )
