---
id: 0406
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:02:15.940899+00:00
status: superseded
corroborations: 1
supersedes: 0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0416
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks (e.g. `scripts/hydraflow_audit/checks/p5_ci.py`) are discovered via `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth for expected checks — registering a check without adding its ADR row (or vice versa) leaves the audit inconsistent. Example: P5.8–P5.10 landed both together. **Why:** ADR-0044 is an Accepted ADR; a check present in code but missing from the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
