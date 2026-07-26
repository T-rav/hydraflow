---
id: 0588
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.331100+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# ADR-0044 P5 checks require both @register() and an ADR table row

`scripts/hydraflow_audit` checks are discovered via `@register("P5.N")`, but the audit also parses `docs/adr/0044-hydraflow-principles.md`'s P5 table as the source of truth — registering a check without adding its ADR row (or vice versa) leaves the audit inconsistent.

Example: P5.8–P5.10 landed both together.

**Why:** ADR-0044 is an Accepted ADR; a check present in code but missing from the table (or the reverse) breaks the audit's self-verification and looks like undocumented drift.
