---
id: 1044
topic: gotchas
source_issue: 10581
source_phase: plan
created_at: 2026-07-26T01:56:36.497406+00:00
status: active
corroborations: 1
---

# Heuristic wiki-drift findings must be report-only, never flip status

New detectors for loose/heuristic signals (e.g. prose-form cites like "`DETECTOR_GENERATION` constant in `escape/detect.py`") must log and count findings but never call `apply_drift_markers` to flip `status: active` → `stale`. In `src/wiki_drift_detector.py`, `detect_prose_drift()` returns `DriftFinding`s that `RepoWikiLoop` only logs and tallies into `stats["prose_drift_suspects"]` (issue #10581), while the strict `detect_drift`/`apply_drift_markers` pair stays byte-for-byte unchanged.

**Why:** a wrong heuristic verdict should cost a log line, not a stale flip across ~395 tracked wiki entries.
