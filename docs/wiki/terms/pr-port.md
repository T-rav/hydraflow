---
id: "01KQV37D10M06PGF32CF77W6K7"
name: "PRPort"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/ports.py:PRPort"
aliases: ["pr port", "pull request port", "github pr port"]
related: [{"kind": "depends_on", "target": "01KR1GDECRP5Z9X3HNGX3XFS8B"}, {"kind": "depends_on", "target": "01KYABD5XVX4ZXFXT3Z76KMQZ0"}, {"kind": "depends_on", "target": "01KYBV9N8VSTKDRVDFC0FE40ZM"}]
evidence: ["01JRC_MOCKWORLD_FAKE_PORT_ASSERTIONS", "01KQNYZRM4B7DX9MWDQFHF488F", "01KRBX2N4QP7VW8FGH3J5YD0M2", "01KRBX2N4QP7VW8FGH3J5YD0M3", "01KRBX2N4QP7VW8FGH3J5YD0M5", "01KRBX2N4QP7VW8FGH3J5YD0M7", "01KXV82K5P3A5RCRB8SHD3C400", "implement-phase-half-state-on-skill-failure"]
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668784+00:00"
updated_at: "2026-07-26T10:16:32.370693+00:00"
---

## Definition

Hexagonal port for GitHub PR, label, and CI operations — branch push, PR creation/merge, RC-branch creation, and the related label manipulations consumed by domain phases and background loops. Implemented by pr_manager.PRManager; signatures are kept identical to the concrete class to enable structural subtype checks.

## Invariants

- Pure Protocol — no implementation, no state.
- Method signatures must match pr_manager.PRManager exactly so structural subtype checks in tests/test_ports.py pass.
