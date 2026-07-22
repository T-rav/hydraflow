---
id: 0354
topic: patterns
source_issue: 10173
source_phase: plan
created_at: 2026-07-22T16:50:02.909708+00:00
status: active
corroborations: 1
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks (e.g. `scripts/hydraflow_audit/checks/p5_ci.py`) are discovered by `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth for which checks are expected to run — registering a check without adding its ADR row (or vice versa) leaves the audit inconsistent. Precedent: P5.8–P5.10 landed both together.

**Why:** ADR-0044 is an Accepted ADR; a check that exists in code but not in the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
