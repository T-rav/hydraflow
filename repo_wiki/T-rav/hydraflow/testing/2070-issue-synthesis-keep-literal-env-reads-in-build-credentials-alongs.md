---
id: 2070
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:54.351443+00:00
status: superseded
corroborations: 1
supersedes: 1945
superseded_by: 2199
---

# Keep literal env reads in build_credentials alongside table

Do not refactor `build_credentials` in `src/config.py` to iterate `CREDENTIAL_ENV_KEYS` — the literal `os.environ.get(...)` / `_dotenv_lookup(...)` chain must stay.

Example: `tests/regressions/test_issue_10885.py` AST-parses `build_credentials` and asserts the extracted key set is non-empty and a subset of declared keys. A loop over the table empties the literal set and turns the gate red.

**Why:** The duplication is intentional — the table is the declaration surface, the function is the readable priority chain, and the gate enforces they agree without collapsing them.
