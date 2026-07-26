"""Trivial production adapters for the flow primitive's injectable hooks.

The :class:`flows.Flow` runtime keeps ``on_node`` / ``checkpoint`` injectable so
the core stays decoupled and unit-testable. This module ships the one adapter
that is genuinely self-contained: a JSONL checkpoint hook backed by
:func:`file_util.append_jsonl` (ADR-0021 persistence, crash-safe fsync +
ADR-0085 secret scrubbing).

The event-bus ``on_node`` hook is deliberately left to the call site: emitting a
per-node telemetry event means choosing an :class:`events.EventType` and payload
shape, which is a phase-conversion (P1+) concern, not a P0 one. Wiring it is a
one-liner at the call site::

    from events import EventType, HydraFlowEvent

    async def on_node(name: str, state: FlowState) -> None:
        await bus.publish(HydraFlowEvent(type=EventType.<...>, data={"node": name}))
"""

from __future__ import annotations

import json
from pathlib import Path

from file_util import append_jsonl

from .flow import FlowState, NodeHook


def jsonl_checkpoint(path: Path) -> NodeHook:
    """Return a ``checkpoint`` hook that appends one JSONL record per node.

    Each record is ``{"node": <name>, "state": <state>}``. The write goes
    through :func:`file_util.append_jsonl`, so it inherits crash-safe fsync and
    ADR-0085 secret scrubbing. Values that are not JSON-serialisable are coerced
    to ``str`` so a checkpoint never crashes the flow it is recording.
    """

    def _checkpoint(node: str, state: FlowState) -> None:
        record = {"node": node, "state": state}
        append_jsonl(path, json.dumps(record, default=str))

    return _checkpoint
