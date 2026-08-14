---
id: 2408
topic: testing
source_issue: 11136
source_phase: plan
created_at: 2026-08-14T13:02:38.765851+00:00
status: active
corroborations: 1
---

# Full-suite triggers must be anchored at repo root

Path-based triggers in `scripts/impacted_tests.py` (e.g., `.claude/**`) match only at the repo root. `docs/claude.md` and `tests/fixtures/.claude/settings.json` must NOT trigger the full suite — only a root-level `.claude/` segment does. Test both directions: root `.claude/settings.json` → full suite; nested `tests/fixtures/.claude/settings.json` → `(frozenset(), None)`.

**Why:** Without root anchoring, nested fixture or doc directories silently re-trigger the full suite.
