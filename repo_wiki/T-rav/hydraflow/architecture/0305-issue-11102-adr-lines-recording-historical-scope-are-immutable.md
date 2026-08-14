---
id: 0305
topic: architecture
source_issue: 11102
source_phase: plan
created_at: 2026-08-14T07:12:44.487617+00:00
status: active
corroborations: 1
---

# ADR lines recording historical scope are immutable, not state claims

Do not edit `docs/adr/0082-declarative-gate-contract.md:24` ("staging from 3 to 2") to match current state. That line records Slice 1's scope at the time of writing, not the current required-check count.

- The grep check `grep -rn "2 required checks\|2 always-on checks" docs/` must explicitly allow ADR-0082's line.
- Treat any ADR sentence describing a *past* configuration as read-only history.

**Why:** Editing historical ADR prose to match current state falsifies the decision record and destroys the audit trail that explains why the architecture evolved.
