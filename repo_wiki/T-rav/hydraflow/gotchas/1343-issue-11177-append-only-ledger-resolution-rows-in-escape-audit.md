---
id: 1343
topic: gotchas
source_issue: 11177
source_phase: plan
created_at: 2026-08-14T22:44:18.538059+00:00
status: active
corroborations: 1
---

# Append-only ledger resolution rows in escape_audit

When resolving escape ledger rows, append a new JSONL row with the resolution; never rewrite prior lines. In `src/escape/auto_diagnose.py`, resolving an issue means adding a new row (last-row-wins) rather than editing the original.

**Why:** Mutating prior rows breaks audit history and causes stale rows (like `14d993ef…`) to re-fire under new issue numbers before the resolution lands.
