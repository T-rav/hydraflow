"""In-framework flow (DAG) primitive (epic #10682, P0).

The foundation the multi-step background workers and pipeline phases are
refactored onto (P1-P3). See :mod:`flows.flow` for the runtime and ADR-0111 for
the phase-execution contract this establishes.
"""

from __future__ import annotations

from .adapters import jsonl_checkpoint
from .flow import (
    DEFAULT_MAX_STEPS,
    Edge,
    EdgeCondition,
    Flow,
    FlowError,
    FlowResult,
    FlowState,
    FlowValidationError,
    KillSwitch,
    Node,
    NodeHook,
    NodeKind,
    NodeRun,
)

__all__ = [
    "DEFAULT_MAX_STEPS",
    "Edge",
    "EdgeCondition",
    "Flow",
    "FlowError",
    "FlowResult",
    "FlowState",
    "FlowValidationError",
    "KillSwitch",
    "Node",
    "NodeHook",
    "NodeKind",
    "NodeRun",
    "jsonl_checkpoint",
]
