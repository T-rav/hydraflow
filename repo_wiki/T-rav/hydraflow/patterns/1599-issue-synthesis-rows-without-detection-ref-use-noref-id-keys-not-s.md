---
id: 1599
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T07:44:05.314873+00:00
status: superseded
corroborations: 1
supersedes: 1514
superseded_by: 1693
---

# Rows without detection_ref use __noref__:<id> keys, not singleton

In `escape_by_id()` (`src/escape/metrics.py`), rows with no `detection_ref` use the synthetic key `__noref__:<id>` so each maps to itself.

Example: Two no-ref rows with ids `a1` and `b2` produce two distinct index entries, not one shared `None` entry.

**Why:** A shared `None` key would collapse unrelated no-ref rows into one, losing entries and silently dropping reconciliations.
