---
id: 1887
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:26.705632+00:00
status: active
corroborations: 1
supersedes: 1789
---

# Rows without detection_ref use __noref__:<id> keys, not singleton

In `escape_by_id()` (`src/escape/metrics.py`), rows with no `detection_ref` use the synthetic key `__noref__:<id>` so each maps to itself.

Example: Two no-ref rows with ids `a1` and `b2` produce two distinct index entries, not one shared `None` entry.

**Why:** A shared `None` key would collapse unrelated no-ref rows into one, losing entries and silently dropping reconciliations.
