---
id: 0918
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:33:17.892870+00:00
status: superseded
corroborations: 1
supersedes: 0860
superseded_by: 0982
---

# Streak guard backstops unclassified credit-signal raise sites

`src/orchestrator.py`'s `_pause_for_credits` should record every credit signal before the FP-cooldown early-return and pause regardless of probe result once ≥`credit_pause_streak_threshold` (default 3, `src/config.py`) distinct sources report within `credit_pause_streak_window_seconds` (default 300).

Example: Key by distinct source, not raw event count, so one chatty diagnostic loop can't trip it alone; recording before the cooldown early-return ensures a cooldown-suppressed source still counts once.

**Why:** Catches a real credit exhaustion whose raise site was missed when tagging `cli` vs `prose` origins, without letting a single noisy loop force a pause.
