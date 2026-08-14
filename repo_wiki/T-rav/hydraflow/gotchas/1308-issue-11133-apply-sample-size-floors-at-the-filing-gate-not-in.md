---
id: 1308
topic: gotchas
source_issue: 11133
source_phase: plan
created_at: 2026-08-14T12:41:23.460395+00:00
status: active
corroborations: 1
---

# Apply sample-size floors at the filing gate, not in math functions

Keep `compute_skill_efficiency` in `src/prompt_efficiency.py` as pure math — always publish the real trend and window size. Apply minimum-sample thresholds in the consumer (`_consume_efficiency_telemetry` in `src/skill_prompt_eval_loop.py`) before calling `_file_inefficiency_issue`.

**Why:** Suppressing the trend inside the math function breaks anchor tests that regenerate expected values (e.g. `+1411%`, `+168%`) through the real function, and hides the signal from the scorecard where under-sampled trends should be visible.
