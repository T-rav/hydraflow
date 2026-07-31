---
id: 0843
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.610569+00:00
status: superseded
corroborations: 1
supersedes: 0788
superseded_by: 0901
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks (e.g. `scripts/hydraflow_audit/checks/p5_ci.py`) are discovered via `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth — both must stay in sync.

Example: P5.8–P5.10 landed both the `@register()` call and the ADR table row together.

**Why:** A check present in code but missing from the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
