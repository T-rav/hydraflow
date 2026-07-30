---
id: 0250
topic: architecture
source_issue: 10753
source_phase: plan
created_at: 2026-07-27T23:48:50.234492+00:00
status: active
corroborations: 1
---

# Expose public API for cross-module repair delegation, avoid _ imports

When `scripts/repair_wiki_supersession.py` calls into `src/wiki_supersession_repair.py`, expose a public `apply_field_updates()` and have the private `_apply_field_updates` delegate to it. Do not import private (`_`-prefixed) functions across module boundaries.

**Why:** Cross-module `_` imports create fragile coupling and break the single-responsibility boundary the repair module enforces; a future rename of the private symbol silently breaks the CLI.
