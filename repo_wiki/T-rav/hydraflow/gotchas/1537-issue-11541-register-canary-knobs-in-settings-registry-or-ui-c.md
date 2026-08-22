---
id: 1537
topic: gotchas
source_issue: 11541
source_phase: plan
created_at: 2026-08-22T00:00:10.177903+00:00
status: active
corroborations: 1
---

# Register canary knobs in settings_registry or UI can't see them

When adding config fields to `src/config.py`, register them in `src/settings_registry.py` in the same PR.

- Canary knobs (phase allowlist, per-repo director cap, issue budget, rollback switch) go in one contiguous block in `src/config.py` with the epic reference.
- `src/settings_registry.py` must expose them with `live=False` (restart-required).

**Why:** The dashboard UI reads from `settings_registry.py`, not `config.py` directly — unregistered fields are invisible to operators despite being parsed by the backend.
