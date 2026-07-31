---
id: 1947
topic: testing
source_issue: 10883
source_phase: plan
created_at: 2026-07-31T07:40:16.906981+00:00
status: active
corroborations: 1
---

# Pin CI workflow shapes with yaml.safe_load in regression tests

Use `yaml.safe_load` in `tests/regressions/` to assert structural rules about `.github/workflows/ci.yml`.
- Assert `Coverage (trailing)` never uses `-p no:xdist`
- Assert exactly one leg carries `--cov-fail-under`

**Why:** Prevents silent regressions in CI configuration—like re-introducing a single-threaded pytest lane that causes chronic 30-minute job cancellations.
