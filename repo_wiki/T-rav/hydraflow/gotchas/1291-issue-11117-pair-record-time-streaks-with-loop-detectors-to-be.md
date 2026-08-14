---
id: 1291
topic: gotchas
source_issue: 11117
source_phase: plan
created_at: 2026-08-14T10:58:30.492002+00:00
status: active
corroborations: 1
---

# Pair record-time streaks with loop detectors to beat weekly cadence lag

When the only consumer of a rate detector is the weekly `SkillPromptEvalLoop` tick, detection lags up to 7 days. Add a record-time consecutive-anomaly streak in `PromptTelemetry._update_pr_stats` that logs ERROR at threshold crossing, so a signal fires inside the burn window. The loop's per-source rate detector in `prompt_efficiency.py` then files the deduped `prompt-zero-usage` issue on its next tick.
- P1 streak channel: fires at record time on the per-source bucket
- P2/P3 rate detector: fires at the weekly loop tick
**Why:** A single weekly-cadence channel let `term_proposer` burn 563 spawns at 100% anomaly with zero signal on any channel.
