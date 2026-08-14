---
id: 0324
topic: architecture
source_issue: 11138
source_phase: plan
created_at: 2026-08-14T14:08:04.915202+00:00
status: active
corroborations: 1
---

# Strip git rev prefix at adapter boundary in escape.auto_diagnose._grep

Normalize `git grep` stdout at the `_grep` adapter (src/escape/auto_diagnose.py) — the one place that knows the rev — not at each consumer. Derive both the argv tree-ish and the stripped prefix from one module constant.

- `lines = [line.removeprefix(REV + ":") for line in stdout.splitlines()]`
- Avoid `split(":", 1)` — repo paths may contain colons and would be mangled.

**Why:** Consumers like `regression_hits` and the HITL close-comment path interpolate strings verbatim; if `HEAD:` leaks through, ledger notes become unopenable and no tool can resolve the path.
