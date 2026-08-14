---
id: 1264
topic: gotchas
source_issue: 11087
source_phase: plan
created_at: 2026-08-14T06:12:02.565888+00:00
status: active
corroborations: 1
---

# Return NA not FAIL for new P8 checks on non-adopting repos

New P8 audit checks (e.g. P8.7 in `scripts/hydraflow_audit/checks/p8_superpowers.py`) must return `NA` for repos that haven't adopted the relevant `hf.*` hook pack, not `FAIL`. Detect adoption by scanning `.claude/hooks/` at runtime — never hardcode hook-path lists. **Why:** An unconditional FAIL turns every fleet repo's Principles Audit red before `make merge-assets` seeds the hook, blocking the rollout.
