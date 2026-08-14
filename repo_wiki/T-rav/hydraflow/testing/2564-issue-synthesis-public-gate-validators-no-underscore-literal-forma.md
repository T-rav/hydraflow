---
id: 2564
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.563500+00:00
status: active
corroborations: 1
supersedes: 2376
---

# Public gate validators: no underscore, literal format strings

Functions in `scripts/gates/validate.py` imported by both `scripts/gen_gates.py` and `tests/regressions/` must be public (no leading `_`). Violation strings must be literal format strings returned in a `list[str]`, not bare variables or exceptions.

Example: branch set comes from `contract.branches` at runtime — never hardcode a path or branch list. Do not duplicate test helpers from `tests/conftest.py`; import or reuse.

**Why:** A private validator forces one consumer to reach into an underscored API; a hardcoded branch list silently misses new branches added to `gates.toml`; bare-variable violations break the `gen-gates --check` exit-code contract.
