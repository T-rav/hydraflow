---
id: 0325
topic: architecture
source_issue: 11140
source_phase: plan
created_at: 2026-08-14T14:36:07.424593+00:00
status: active
corroborations: 1
---

# Expose tunable thresholds as kwargs, not module constants alone

`pick_refine_order` in `src/prompt_efficiency.py` accepts `min_window_calls` as a keyword arg (defaulting to the module-level `MIN_WINDOW_CALLS`) so callers and tests can vary the sample-size floor without monkeypatching.

- Production caller: uses default
- Tests: pass `min_window_calls=...` to demote or promote sources across tiers

**Why:** Hardcoding the threshold makes tier-boundary tests brittle and forces global state mutation to exercise edge cases.
