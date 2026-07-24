---
id: 0436
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:06:34.701164+00:00
status: active
corroborations: 1
supersedes: 0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks (e.g. `scripts/hydraflow_audit/checks/p5_ci.py`) are discovered via `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth for expected checks — registering a check without adding its ADR row (or vice versa) leaves the audit inconsistent. Example: P5.8–P5.10 landed both together. **Why:** ADR-0044 is an Accepted ADR; a check present in code but missing from the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
