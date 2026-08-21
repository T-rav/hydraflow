---
id: 4080
topic: patterns
source_issue: 11533
source_phase: plan
created_at: 2026-08-21T09:41:01.976049+00:00
status: active
corroborations: 1
---

# Amend, don't supersede, when only one ADR passage is wrong

When a new ADR scopes down one passage of an Accepted ADR while its core decision stands, write the relationship as **Amends**, not Supersedes.
- ADR-0135 amends ADR-0094: the two-level gate/ledger decision stands; only the blocking-shepherd *alternatives* rejection is narrowed to the convergence-outer-loop context (ADR-0107 precedent).
- Add an amendment note in the amended ADR body plus an index entry in `docs/adr/README.md`; verify the target number is still free at implementation time.
**Why:** Supersession would invalidate still-correct decisions and break every cross-reference that cites them.
