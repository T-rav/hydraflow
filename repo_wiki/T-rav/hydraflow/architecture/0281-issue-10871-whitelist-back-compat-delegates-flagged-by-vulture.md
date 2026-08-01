---
id: 0281
topic: architecture
source_issue: 10871
source_phase: plan
created_at: 2026-07-31T06:30:13.825334+00:00
status: stale
corroborations: 1
stale_reason: source issue #10871 closed
---

# Whitelist back-compat delegates flagged by vulture, do not remove

When a back-compat delegate (e.g. `_load_audit_module` in `src/prompt_fitness.py`) reads as unused inside `src/` because all internal call sites migrated to the public name, vulture will flag it. Whitelist or annotate the delegate rather than removing it.

**Why:** The delegate exists for unknown external callers; deleting it to satisfy a lint pass silently breaks back-compat and defeats the rename-plus-delegate pattern.
