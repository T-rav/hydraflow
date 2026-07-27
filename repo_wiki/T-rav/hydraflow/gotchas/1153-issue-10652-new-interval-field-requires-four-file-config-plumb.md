---
id: 1153
topic: gotchas
source_issue: 10652
source_phase: plan
created_at: 2026-07-26T16:08:03.465328+00:00
status: active
corroborations: 1
---

# New interval field requires four-file config plumbing

Adding a `*_interval` config field to `src/config.py` requires coordinated edits across four files:

- `src/config.py` — field with `ge`/`le` bounds + `("field", "HYDRAFLOW_ENV", default)` in env override table
- `tests/helpers.py` — thread through `make_bg_loop_deps`
- `tests/test_config_consistency.py` — add to `_INTERVAL_BOUNDS_SKIP` if not operator-editable
- `docs/arch/generated/loops.md` — regenerate via `make arch-regen`

**Why:** Missing any one causes either config-consistency failures, test-fixture KeyError, or uncommitted generated artifacts.
