---
id: 1383
topic: gotchas
source_issue: 11218
source_phase: plan
created_at: 2026-08-15T06:29:26.164532+00:00
status: active
corroborations: 1
---

# Never clean -x in factory boot sync; .venv must survive

Use `git clean -fd` in `scripts/run-factory-isolated.sh`, never `clean -x`. Gitignored `.venv/` must survive each boot sync.

- `clean -x` strips gitignored paths, forcing a full pip reinstall on every factory boot.
- Untracked residue like `tests/regressions/test_issue_*.py` is still removed by `-fd` without `-x`.

**Why:** A full `.venv` reinstall per boot turns a seconds-long sync into a minutes-long cold start with no benefit — the clone is disposable but the venv is not.
