---
id: 1945
topic: testing
source_issue: 10885
source_phase: plan
created_at: 2026-07-31T07:40:02.824238+00:00
status: active
corroborations: 1
---

# Keep literal env reads in build_credentials alongside CREDENTIAL_ENV_KEYS

Do not refactor `build_credentials` in `src/config.py` to iterate `CREDENTIAL_ENV_KEYS` — the literal `os.environ.get(...)` / `_dotenv_lookup(...)` chain must stay.

- `tests/regressions/test_issue_10885.py` AST-parses `build_credentials` and asserts the extracted key set is non-empty and a subset of declared keys.
- A loop over the table empties the literal set and turns the gate red.

**Why:** The duplication is intentional — the table is the declaration surface, the function is the readable priority chain, and the gate enforces they agree without collapsing them.
