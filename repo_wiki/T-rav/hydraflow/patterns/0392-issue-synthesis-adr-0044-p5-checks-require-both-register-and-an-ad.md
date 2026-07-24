---
id: 0392
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.606824+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks (e.g. `scripts/hydraflow_audit/checks/p5_ci.py`) are discovered by `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth for which checks are expected to run. Registering a check without adding its ADR row (or vice versa) leaves the audit inconsistent.

Example: P5.8–P5.10 landed both together.

**Why:** ADR-0044 is an Accepted ADR; a check that exists in code but not in the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
