---
id: 2586
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.891324+00:00
status: active
corroborations: 1
supersedes: 2401
---

# merge_settings_file must be idempotent across repeated runs

Re-running `merge_settings_file` on an already-merged target must not duplicate HydraFlow hooks — each tagged hook appears exactly once per matcher.

Example: the P2 idempotency test merges twice and asserts no duplicate entries; managed repos are re-onboarded via `make setup-target`, so repeat merges are expected.

**Why:** Duplicate hooks cause silent double-execution of scripts like `hf.secret_scan.py` or `hf.destructive_git.py`, and stale untagged state in already-onboarded repos is repaired by re-running the idempotent merge.
