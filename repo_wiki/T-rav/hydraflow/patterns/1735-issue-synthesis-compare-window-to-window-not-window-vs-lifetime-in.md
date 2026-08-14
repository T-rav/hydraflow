---
id: 1735
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T11:12:32.492979+00:00
status: superseded
corroborations: 1
supersedes: 1642
superseded_by: 1831
---

# Compare window-to-window, not window-vs-lifetime, in skill efficiency

Use the prior tick's window rate as the trend baseline — never a lifetime-cumulative average.

Example: `compute_skill_efficiency` in `skill_prompt_eval_loop.py` derives `trend_vs_baseline`; it must read a stored prior window rate, not `baseline.cost/baseline.calls`. A lifetime average straddles provider eras (e.g. claude/sonnet→zai/glm-5.2 swap at call #564), making marginal-window comparisons meaningless. Return `trend=None` when no prior window exists.

**Why:** A window-vs-lifetime comparison can manufacture a +168% filing from a source whose per-billed-call cost actually fell ~10%.
