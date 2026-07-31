---
id: 2253
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.844676+00:00
status: active
corroborations: 1
supersedes: 2108
---

# ADR-text + static/unit test fixes skip MockWorld/e2e

For ADR-text-only fixes paired with static or unit tests (no runtime logic change to `src/`), skip MockWorld scenario and sandbox e2e layers despite the repo's usual three-layer pyramid.

Example: a pure ADR-text repair plus one behavioral unit test in `tests/test_triage_phase.py`; or an ADR-citation drift fix plus a static test over `_SOURCE_FILE_CITATION_RE`. See also: testing — Pure-function + log-line changes skip MockWorld/sandbox e2e.

**Why:** Load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface for MockWorld or e2e to exercise.
