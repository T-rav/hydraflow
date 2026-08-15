---
id: 2401
topic: testing
source_issue: 11124
source_phase: plan
created_at: 2026-08-14T11:33:53.102511+00:00
status: superseded
corroborations: 1
superseded_by: 2586
---

# merge_settings_file must be idempotent across repeated runs

Re-running `merge_settings_file` on an already-merged target must not duplicate HydraFlow hooks — each tagged hook appears exactly once per matcher.

The P2 idempotency test merges twice and asserts no duplicate entries; managed repos are re-onboarded via `make setup-target`, so repeat merges are expected.

**Why:** Duplicate hooks cause silent double-execution of scripts like `hf.secret_scan.py` or `hf.destructive_git.py`, and stale untagged state in already-onboarded repos is repaired by re-running the idempotent merge.
