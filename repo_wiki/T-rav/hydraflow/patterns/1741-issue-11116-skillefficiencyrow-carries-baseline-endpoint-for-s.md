---
id: 1741
topic: patterns
source_issue: 11116
source_phase: plan
created_at: 2026-08-14T10:10:56.158163+00:00
status: active
corroborations: 1
---

# SkillEfficiencyRow carries baseline endpoint for self-contained filings

`compute_skill_efficiency` stamps `baseline_calls`/`baseline_cost_usd` (default `None`) onto each `SkillEfficiencyRow`. Filed `prompt-inefficiency` bodies then print baseline → current endpoints without replaying `inferences.jsonl`. Missing baseline renders as "no prior baseline", never `None` or a raise.

**Why:** Triage must reproduce the filed window from state alone; `None`/raises break the filing path on first tick or new source.
