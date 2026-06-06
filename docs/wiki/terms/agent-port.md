---
id: "01KT3WKPR5MN8QJ14CF77W6K8"
name: "AgentPort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:AgentPort"
aliases: ["agent port", "agent runner port"]
related: [{"kind": "depends_on", "target": "01KR1GDECRP5Z9X3HNGX3XFS8B"}, {"kind": "depends_on", "target": "01KTANBHSTGWNRXS6M142101ED"}, {"kind": "depends_on", "target": "01KTANCQNKWYRJ5ETEVNAMEY5A"}, {"kind": "depends_on", "target": "01KTBHAP0E4RHCFZVEC1P12QQM"}]
evidence: ["01KQP0XFBGMB32VFGNPV8GZ26X"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T00:00:00.000000+00:00"
updated_at: "2026-06-06T01:04:43.481148+00:00"
---

## Definition

Hexagonal port for agent runner operations used by infrastructure modules. Implemented by `agent.AgentRunner` via `base_runner.BaseRunner`. The port was introduced so that infrastructure modules like `merge_conflict_resolver` can accept the agent runner via dependency injection without importing from the runner layer, keeping the four-layer boundary clean and making those modules independently testable with a mock.

## Invariants

- Pure Protocol — no implementation, no state.
- Three methods: `build_command` constructs the CLI invocation; `execute` runs the subprocess and returns the full transcript; `verify_result` checks that the agent produced valid commits and that `make quality` passes.
- Parameter names and types are kept identical to the concrete implementations to satisfy structural subtype checks in `tests/test_ports.py`.
