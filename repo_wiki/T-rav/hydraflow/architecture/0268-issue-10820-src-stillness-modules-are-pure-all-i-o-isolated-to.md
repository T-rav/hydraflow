---
id: 0268
topic: architecture
source_issue: 10820
source_phase: plan
created_at: 2026-07-31T00:58:39.724623+00:00
status: active
corroborations: 1
---

# src/stillness/ modules are pure; all I/O isolated to scripts/

Keep `src/stillness/{models,series,rank,report}.py` free of `subprocess`, `httpx`, and `requests`. All `gh`/`git` reads and their JSON cache live in `scripts/oscillation_fingerprint.py`, so re-runs are offline and deterministic. An architecture test pins both the import boundary and loop-classification coverage.

- Pure modules: `src/stillness/{models,series,rank,report}.py`
- I/O + cache: `scripts/oscillation_fingerprint.py`

**Why:** Prevents the reporting tool from becoming a mutating loop and enables byte-identical re-runs over a fixed cache.
