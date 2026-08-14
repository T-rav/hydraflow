---
id: 1287
topic: gotchas
source_issue: 11113
source_phase: plan
created_at: 2026-08-14T09:30:40.586288+00:00
status: active
corroborations: 1
---

# Keep ui-npm.sh exec path byte-identical to support stand-in nvm pin

The `--can-run` probe must use the same exec verbs as the run path (`nvm exec "$v" npm "$@"`, `fnm exec --using=`, `volta run --node`, brew prefix `-x` check) — never switch to `nvm which` or `nvm ls`.

**Why:** `tests/regressions/test_issue_11113.py`'s stand-in nvm implements only `install`/`exec`; changing probe verbs makes the pin fail for the wrong reason and lets the real divergence bug resurface undetected.
