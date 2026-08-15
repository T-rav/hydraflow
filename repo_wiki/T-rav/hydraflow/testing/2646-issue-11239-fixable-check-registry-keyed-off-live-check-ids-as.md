---
id: 2646
topic: testing
source_issue: 11239
source_phase: plan
created_at: 2026-08-15T09:47:55.217009+00:00
status: active
corroborations: 1
---

# Fixable check registry keyed off live check_ids, asserted orphan-free

Key fixable classification off live registered check_ids, never a hardcoded path list; assert the registry is orphan-free in tests. `scripts/hydraflow_audit/fixable.py`: `FIXABLE: dict[check_id, fixer_id]` + `is_fixable()`. `runner._run_one` stamps `Finding.fixable`; `Finding.to_dict()` emits it so report layers inherit it. **Why:** A hardcoded list silently decouples from the audit registry as checks are added or renamed.
