---
id: 0960
topic: patterns
source_issue: 10865
source_phase: plan
created_at: 2026-07-31T02:25:44.330115+00:00
status: superseded
corroborations: 1
superseded_by: 1024
---

# Sync ADR measurement contracts with detector logic

When modifying detection logic tied to an ADR contract, update the corresponding ADR section concurrently. If changing `src/prompt_fitness.py` stripping rules, amend `docs/adr/0116-prompts-as-a-measured-contract.md` §10 and add a §9 correction note.
**Why:** Fixing code without updating the ADR causes ADR-drift, where the documented measurement contract no longer reflects the CI gate behavior.
