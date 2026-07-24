---
id: 0377
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:53:43.447206+00:00
status: superseded
corroborations: 1
supersedes: 0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0388
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks (e.g. `scripts/hydraflow_audit/checks/p5_ci.py`) are discovered by `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth for which checks are expected to run — registering a check without adding its ADR row (or vice versa) leaves the audit inconsistent.

Example: P5.8–P5.10 landed both together.

**Why:** ADR-0044 is an Accepted ADR; a check that exists in code but not in the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
