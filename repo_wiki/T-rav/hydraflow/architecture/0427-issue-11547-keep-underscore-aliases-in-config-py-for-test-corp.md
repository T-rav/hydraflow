---
id: 0427
topic: architecture
source_issue: 11547
source_phase: plan
created_at: 2026-08-30T07:44:19.983865+00:00
status: active
corroborations: 1
---

# Keep _underscore aliases in config.py for test corpus imports

When extracting from `src/config.py`, re-export moved symbols under their original `_underscore` names even though new modules expose public names. The wide test corpus (21 `tests/test_config_*.py` files) does `from config import _ENV_BOOL_OVERRIDES`, `from config import _apply_env_overrides`, and `from config import _parse_combo` directly.
- New modules use public names; `config.py` keeps `_` aliases as re-exports
**Why:** A dropped alias breaks distant tests with no obvious link to the extraction diff, causing a green-locally-red-CI failure.
