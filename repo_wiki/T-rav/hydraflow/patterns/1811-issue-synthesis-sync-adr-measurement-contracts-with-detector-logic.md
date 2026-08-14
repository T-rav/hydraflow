---
id: 1811
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T12:50:04.145069+00:00
status: active
corroborations: 1
supersedes: 1715
---

# Sync ADR measurement contracts with detector logic

When modifying detection logic tied to an ADR contract, update the corresponding ADR section concurrently.

Example: If changing `src/prompt_fitness.py` stripping rules, amend `docs/adr/0116-prompts-as-a-measured-contract.md` §10 and add a §9 correction note.

**Why:** Fixing code without updating the ADR causes ADR-drift, where the documented measurement contract no longer reflects the CI gate behavior.
