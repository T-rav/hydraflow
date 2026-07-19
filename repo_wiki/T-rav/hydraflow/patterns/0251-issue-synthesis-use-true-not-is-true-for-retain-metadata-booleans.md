---
id: 0251
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.229731+00:00
status: superseded
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
superseded_by: 0260
---

# Use `== "true"`, not `is True` for `retain()` metadata booleans

`HindsightClient.retain()` calls `str(v)` on all metadata values; boolean `True` becomes string `"true"`.

Example: `metadata={"warning": "true"}` not `{"warning": True}`; check with `metadata.get("warning") == "true"`.

**Why:** `metadata.get("warning") is True` always returns `False` after coercion, silently disabling warning-based filtering.
