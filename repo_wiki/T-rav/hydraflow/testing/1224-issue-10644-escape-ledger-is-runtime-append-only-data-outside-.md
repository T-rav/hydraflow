---
id: 1224
topic: testing
source_issue: 10644
source_phase: plan
created_at: 2026-07-26T12:01:31.012822+00:00
status: active
corroborations: 1
---

# Escape ledger is runtime append-only data outside the repo

The escape ledger lives at `config.diagnostics_dir/escape_ledger.jsonl` — runtime data, never committed. `append_resolution` writes a superseding row; it never rewrites existing rows.

- A PR can fix the render path and tests, but cannot close an already-surfaced escape issue by committing a resolution row.
- An operator must run `make escape-resolve … --encoded-as <value> --confidence <value>` to append the closing row at runtime.

**Why:** Committing runtime ledger data breaks the append-only invariant and couples test fixtures to mutable operator state.
