---
id: 0041
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.319646+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# HindsightClient.retain() coerces metadata to `str` — use `== "true"`, not `is True`

`retain()` calls `str(v)` on all metadata values; boolean `True` becomes string `"true"`.

Example: `metadata={"warning": "true"}` not `{"warning": True}`; check with `metadata.get("warning") == "true"`.

**Why:** `metadata.get("warning") is True` always returns `False` after coercion, silently disabling warning-based filtering.
