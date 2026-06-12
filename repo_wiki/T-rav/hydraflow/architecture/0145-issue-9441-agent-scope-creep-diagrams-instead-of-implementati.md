---
id: 0145
topic: architecture
source_issue: 9441
source_phase: review
created_at: 2026-06-12T13:54:23.578686+00:00
status: active
corroborations: 1
---

# Agent scope creep: diagrams instead of implementation

An agent that understands a problem may commit architecture diagrams (LikeC4, Mermaid flows) without delivering required code. Correct diagrams prove understanding, not implementation.

- `docs/architecture/pipeline_poller_scenario.likec4` being accurate does not mean any test file was created.
- If unplanned diagram files appear and planned code files are missing, verdict is null delivery.

**Why:** A reviewer who finds well-structured diagrams may infer progress; the actual acceptance criteria (test files, shims, constants) remain entirely unmet.
