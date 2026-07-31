---
id: 1949
topic: testing
source_issue: 10883
source_phase: plan
created_at: 2026-07-31T07:40:16.907027+00:00
status: active
corroborations: 1
---

# pytest-cov 7.0.0 and xdist worker data combination is safe

Ignore stale workflow comments claiming `xdist + --cov is finicky` in this repo.
- `pytest-cov` 7.0.0 combines worker coverage data correctly
- Use `--dist loadscope` and `--cov-append`

**Why:** Operating under the stale assumption forced single-threaded coverage runs (`-p no:xdist`), causing chronic `Coverage (trailing)` cancellations at the 30-minute mark.
