---
id: 0571
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:39:17.784840+00:00
status: active
corroborations: 1
supersedes: 0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539,0540,0542,0543,0544,0545,0546,0547,0548,0549
---

# Streak guard backstops unclassified credit-signal raise sites

`src/orchestrator.py`'s `_pause_for_credits` should record every credit signal (before the FP-cooldown early-return) and pause regardless of probe result once ≥`credit_pause_streak_threshold` (config default 3, `src/config.py`) *distinct* sources report within `credit_pause_streak_window_seconds` (default 300).

Example: key by distinct source, not raw event count, so one chatty diagnostic loop can't trip it alone; recording before the cooldown early-return ensures a cooldown-suppressed source still counts once.

**Why:** catches a real credit exhaustion whose raise site was missed when tagging `cli` vs `prose` origins, without letting a single noisy loop force a pause.
