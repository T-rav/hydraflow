"""Tests for ``plan_phase_flow`` — the ADR-0111 per-issue plan graph.

``_build_plan_flow`` is the *shape* of planning: which node runs, and which
fail-closed exits skip the tail. ``Flow`` itself validates connectivity at
construction, so these tests pin the things validation cannot see — that every
node is bound to the mixin method named after it, that the three fail-closed
exits (``prepass`` / ``route`` / ``gate`` -> ``done``) are declared BEFORE
their unconditional siblings (first-match-wins routing makes declaration order
load-bearing), and that the sole LLM actuator sits on the ``draft`` node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from plan_phase_common import _flow_stopped
from tests.helpers import make_plan_phase

if TYPE_CHECKING:
    from config import HydraFlowConfig

_EXPECTED_NODES = {
    "prepass": "gate",
    "surface": "step",
    "draft": "step",
    "ensemble": "loop",
    "route": "gate",
    "write-records": "step",
    "gate": "gate",
    "ready": "step",
    "done": "step",
}


@pytest.fixture
def flow(config: HydraFlowConfig):
    phase, *_ = make_plan_phase(config)
    return phase._build_plan_flow(), phase


class TestPlanFlowShape:
    def test_entry_is_the_prepass_gate(self, flow) -> None:
        built, _ = flow
        assert built.entry == "prepass"

    def test_node_set_and_kinds_match_the_documented_dag(self, flow) -> None:
        built, _ = flow
        assert {
            name: node.kind for name, node in built._nodes.items()
        } == _EXPECTED_NODES

    def test_every_node_runs_its_like_named_mixin_method(self, flow) -> None:
        built, phase = flow
        bound = {
            name: getattr(phase, f"_flow_{name.replace('-', '_')}")
            for name in _EXPECTED_NODES
        }
        assert {name: node.run for name, node in built._nodes.items()} == bound

    def test_fail_closed_exits_are_guarded_by_the_stop_predicate(self, flow) -> None:
        built, _ = flow
        guarded = {(e.src, e.dst) for e in built._edges if e.when is _flow_stopped}
        assert guarded == {("prepass", "done"), ("route", "done"), ("gate", "done")}

    @pytest.mark.parametrize("src", ["prepass", "route", "gate"])
    def test_stop_edge_precedes_its_unconditional_sibling(self, flow, src) -> None:
        # First-match-wins: an unconditional edge declared first would swallow
        # every fail-closed exit from that node.
        built, _ = flow
        outgoing = built._outgoing[src]
        assert outgoing[0].when is _flow_stopped
        assert outgoing[0].dst == "done"
        assert outgoing[1].when is None


class TestInitialPlanState:
    def test_seeds_only_the_index_and_the_issue(self, config: HydraFlowConfig) -> None:
        phase, *_ = make_plan_phase(config)
        issue = object()

        assert phase._initial_plan_state(3, issue) == {"idx": 3, "issue": issue}
