---
id: 0279
topic: architecture
source_issue: 10871
source_phase: plan
created_at: 2026-07-31T06:30:13.825283+00:00
status: active
corroborations: 1
---

# Rename-plus-delegate: public owns impl, private delegates

When promoting a `_`-prefixed symbol to public API across a module boundary, move the implementation into the public name and make the private name a one-line delegate that calls it. Precedent: `src/repo_wiki.py` (`split_tracked_entry` wrapping `_split_tracked_entry`); applied in `src/prompt_fitness.py` for `load_audit_module`/`_load_audit_module`.

- Public name: full body, signature, docstring.
- Private name: `return public_name(...)` only.
- Migrate all in-module call sites to the public name.

**Why:** Delegate, never duplicate — prevents the two names from diverging silently while keeping unknown external callers working.
