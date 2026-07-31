---
id: 0901
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:33:17.848134+00:00
status: active
corroborations: 1
supersedes: 0843
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks are discovered via `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth — both must stay in sync.

Example: P5.8–P5.10 landed both the `@register()` call and the ADR table row together.

**Why:** A check present in code but missing from the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
