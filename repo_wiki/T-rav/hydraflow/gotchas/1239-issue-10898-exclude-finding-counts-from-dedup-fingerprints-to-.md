---
id: 1239
topic: gotchas
source_issue: 10898
source_phase: plan
created_at: 2026-07-31T11:06:20.726244+00:00
status: active
corroborations: 1
---

# Exclude finding counts from dedup fingerprints to prevent re-filing

Keep `skipped_runs`, `runs_searched`, and other count-derived fields out of fingerprint inputs in `find_born_broken`, `find_uncorrelated_blame`, `find_suspected_hangs` (`src/gate_health_loop.py`).

- Same window ticked twice → finding filed once
- Count fields appear only in rendered evidence bodies via `_render_finding`

**Why:** If counts entered the fingerprint, each tick over an unchanged window would produce a new fingerprint and refile the same issue, defeating dedup.
