---
id: 2884
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:52.231041+00:00
status: active
corroborations: 1
supersedes: 2755
---

# Compare window-to-window, not window-vs-lifetime, in skill efficiency

Use the prior tick's window rate as the trend baseline — never a lifetime-cumulative average.

Example: `compute_skill_efficiency` in `skill_prompt_eval_loop.py` must read a stored prior window rate, not `baseline.cost/baseline.calls`. A lifetime average straddles provider eras, making marginal-window comparisons meaningless. Return `trend=None` when no prior window exists. See also: [patterns] — Cost-per-call denominator must exclude usage_unavailable_calls.

**Why:** A window-vs-lifetime comparison can manufacture a +168% filing from a source whose per-billed-call cost actually fell ~10%.
