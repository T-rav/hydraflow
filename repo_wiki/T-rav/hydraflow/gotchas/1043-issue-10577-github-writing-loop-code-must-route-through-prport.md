---
id: 1043
topic: gotchas
source_issue: 10577
source_phase: plan
created_at: 2026-07-26T01:40:01.589377+00:00
status: active
corroborations: 1
---

# GitHub-writing loop code must route through PRPort and reraise credit/bug errors

New GitHub-side effects added to `EscapeLedgerLoop` (e.g. commenting on and closing an issue via `close_issue`) must go through `PRPort`, not a direct client call, and any broad `except` around that call must include `reraise_on_credit_or_bug(exc)` per the dark-factory contract (docs/wiki/dark-factory.md §2.2). A failing `close_issue` should leave the link row open for retry rather than marking it closed.

**Why:** skipping `reraise_on_credit_or_bug` silently eats `CreditExhaustedError` and burns attempt budget against an already-exhausted billing signal.
