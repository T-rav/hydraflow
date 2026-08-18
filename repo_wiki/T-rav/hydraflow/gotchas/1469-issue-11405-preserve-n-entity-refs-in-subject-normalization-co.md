---
id: 1469
topic: gotchas
source_issue: 11405
source_phase: plan
created_at: 2026-08-18T02:33:46.704096+00:00
status: active
corroborations: 1
---

# Preserve #N entity refs in subject normalization, collapse bare digits

Rule: In churn-miner subject keys (`src/detector_calibration_loop.py:_normalize`), emit `#`-prefixed digit runs verbatim and collapse all other digit runs to `#`. This keeps PR/issue refs (`#10809`, `#11241`) distinct while bare counters (`after 3 retries`, `elapsed 45s`) fold together.
- Do not widen identity beyond the `#N` form — decimals (`$45.20`), line numbers, and bare counts must keep collapsing.
- A survey confirmed no escalation title in this repo uses `#N` for a volatile value.

**Why:** Folding distinct PRs onto `pr ##` makes the churn-miner file false "churned 3x" findings about itself.
