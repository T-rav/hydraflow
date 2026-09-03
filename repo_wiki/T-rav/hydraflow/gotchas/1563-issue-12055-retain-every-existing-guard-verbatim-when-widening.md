---
id: 1563
topic: gotchas
source_issue: 12055
source_phase: plan
created_at: 2026-09-02T21:55:38.779819+00:00
status: active
corroborations: 1
---

# Retain every existing guard verbatim when widening compliance scans

When generalizing a security check, preserve all guards: Dockerfile.agent absence probes, UnicodeError skip, >5000-byte anti-vacuity floor, self-exemption, and `tests/**/fixtures/**` synthetic-data exemption.

Example: test_beads_manager.py's existing guards must stay in place during the corpus-widening refactor in issue #12055.

**Why:** Removing guards to reduce false positives often re-enables the original bug (PR #8460 over-pruned getattr checks; hotfix PR #8463 followed).
