---
id: 0604
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.349194+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Streak guard backstops unclassified credit-signal raise sites

`src/orchestrator.py`'s `_pause_for_credits` should record every credit signal before the FP-cooldown early-return and pause regardless of probe result once ≥`credit_pause_streak_threshold` distinct sources report within `credit_pause_streak_window_seconds`.

Example: key by distinct source, not raw event count, so one chatty diagnostic loop can't trip it alone.

**Why:** catches real credit exhaustion whose raise site was missed when tagging `cli` vs `prose` origins, without letting a single noisy loop force a pause.
