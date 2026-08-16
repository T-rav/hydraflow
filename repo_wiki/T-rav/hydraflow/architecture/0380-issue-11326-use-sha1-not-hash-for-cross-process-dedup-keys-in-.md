---
id: 0380
topic: architecture
source_issue: 11326
source_phase: plan
created_at: 2026-08-16T09:29:42.917610+00:00
status: active
corroborations: 1
---

# Use sha1, not hash(), for cross-process dedup keys in hydraflow

Use `hashlib.sha1(..., usedforsecurity=False)` when generating stable class keys like `generate_class_key` in `src/class_key.py`. Avoid `hash()` entirely.

Example: `hashlib.sha1(pattern.encode(), usedforsecurity=False).hexdigest()[:12]`

**Why:** `PYTHONHASHSEED` randomizes `hash()` across interpreters, breaking the cross-tick matching stability required by Child 3.
