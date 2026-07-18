---
id: 0083
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:09:01.911494+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# `retain()` coerces metadata to `str` — use `== "true"`, not `is True`

`HindsightClient.retain()` calls `str(v)` on all metadata values; boolean `True` becomes string `"true"`.

Example: `metadata={"warning": "true"}` not `{"warning": True}`; check with `metadata.get("warning") == "true"`.

**Why:** `metadata.get("warning") is True` always returns `False` after coercion, silently disabling warning-based filtering.
