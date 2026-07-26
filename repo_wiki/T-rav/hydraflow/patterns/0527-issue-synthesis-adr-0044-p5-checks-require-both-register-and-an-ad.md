---
id: 0527
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.234464+00:00
status: active
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks (e.g. `scripts/hydraflow_audit/checks/p5_ci.py`) are discovered via `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth — registering a check without adding its ADR row (or vice versa) leaves the audit inconsistent.

Example: P5.8–P5.10 landed both together.

**Why:** ADR-0044 is an Accepted ADR; a check present in code but missing from the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
