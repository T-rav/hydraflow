---
id: 0521
topic: patterns
source_issue: 10558
source_phase: plan
created_at: 2026-07-25T23:16:50.588366+00:00
status: superseded
corroborations: 1
superseded_by: 0523
---

# Streak guard backstops unclassified credit-signal raise sites

`src/orchestrator.py`'s `_pause_for_credits` should record every credit signal (before the FP-cooldown early-return) and pause regardless of probe result once ≥`credit_pause_streak_threshold` (config default 3, `src/config.py`) *distinct* sources report within `credit_pause_streak_window_seconds` (default 300).
- Key by distinct source, not raw event count, so one chatty diagnostic loop can't trip it alone.
- Recording before the cooldown early-return ensures a cooldown-suppressed source still counts once.
**Why:** catches a real credit exhaustion whose raise site was missed when tagging `cli` vs `prose` origins, without letting a single noisy loop force a pause.
