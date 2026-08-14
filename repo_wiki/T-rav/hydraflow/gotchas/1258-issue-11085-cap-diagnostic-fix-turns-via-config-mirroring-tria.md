---
id: 1258
topic: gotchas
source_issue: 11085
source_phase: plan
created_at: 2026-08-14T05:58:31.318334+00:00
status: active
corroborations: 1
---

# Cap diagnostic fix turns via config, mirroring triage_max_turns

Add a `diagnostic_fix_max_turns` field to `src/config.py` with an env-alias entry, defaulting to a value well above the median but far below runaway outliers (default 60; median ≈ 10–25, outlier ≈ 215). Pass it into the Stage-2 `_build_command` in `src/diagnostic_runner.py`.

- Stage-1 diagnose is read-only and stays uncapped.
- A capped-out session must surface as a **failed fix**, not a silent success.

**Why:** Without a turn bound, heavy-tailed sessions (3196s, $15.86) recur and dominate `diagnostic_fix` spend.
