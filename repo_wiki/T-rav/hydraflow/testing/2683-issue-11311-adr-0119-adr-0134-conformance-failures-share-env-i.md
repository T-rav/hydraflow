---
id: 2683
topic: testing
source_issue: 11311
source_phase: plan
created_at: 2026-08-16T07:14:25.767556+00:00
status: active
corroborations: 1
---

# ADR-0119/ADR-0134 conformance failures share env-isolation root

When multiple ADR conformance tests fail with credential-reroute assertions, suspect env-scrub isolation before source logic.

- #11311, #11312, #11302 (13 tests total) all close from one `tests/conftest.py` scrub-surface fix.
- Verify root cause with `env -u ZAI_API_KEY -u ZAI_CODING_PLAN_KEY pytest ...`; if green, the source is correct.
- Whichever sibling lands first, the others' pins go green — expect a `conftest.py` merge conflict if concurrent.

**Why:** Patching the source instead of the scrub masks the leak and leaves sibling conformance tests red.
