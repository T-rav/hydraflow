---
id: 0297
topic: architecture
source_issue: 11084
source_phase: plan
created_at: 2026-08-14T05:53:19.138448+00:00
status: active
corroborations: 1
---

# Ledger is append-only; cross-module symbols drop the underscore

Resolution is a new JSONL row via `resolve_escape` — never rewrite existing lines. New cross-module lookups on `EscapeDiagnosisLedger` must omit the leading `_` (the private prefix is module-local convention).
- Reuse `tests/helpers.make_bg_loop_deps` for loop-deps fakes; don't add helpers.
- Keep `logger.warning` on a literal format string with `%s` args.
- No new `subprocess`/`gh` outside the existing `PRPort`/git-read seam.
**Why:** Rewriting ledger lines breaks audit history; `_`-prefixed cross-module symbols are unreachable from the loop; new subprocess seams bypass the `escape_ledger_auto_diagnose_enabled` kill-switch.
