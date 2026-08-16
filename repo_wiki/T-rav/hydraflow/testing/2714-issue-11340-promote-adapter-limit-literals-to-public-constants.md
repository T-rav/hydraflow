---
id: 2714
topic: testing
source_issue: 11340
source_phase: plan
created_at: 2026-08-16T11:56:57.838094+00:00
status: active
corroborations: 1
---

# Promote adapter --limit literals to public constants for fake parity

When a fake must slice to the same window as the real adapter, promote the adapter's hard-coded `--limit` values to public module constants the fake can import.

- `LABEL_ISSUE_LIST_LIMIT = 100` and `OPEN_ISSUE_LIST_LIMIT = 500` in `src/pr_manager.py`, imported by `src/mockworld/fakes/fake_github.py`.
- Counter-pin test: stub `PRManager._run_gh` to capture argv, assert adapter's `--limit` equals the constant the fake slices on.

**Why:** Hard-coded literals invisible to the fake create silent drift — raising the adapter's cap without updating the fake passes tests but diverges from production.
