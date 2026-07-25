---
id: 0503
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:12:20.634382+00:00
status: active
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks (e.g. `scripts/hydraflow_audit/checks/p5_ci.py`) are discovered via `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth — registering a check without adding its ADR row (or vice versa) leaves the audit inconsistent.

Example: P5.8–P5.10 landed both together.

**Why:** ADR-0044 is an Accepted ADR; a check present in code but missing from the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
