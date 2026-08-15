---
id: 1399
topic: gotchas
source_issue: 11241
source_phase: plan
created_at: 2026-08-15T10:09:34.777702+00:00
status: active
corroborations: 1
---

# escape-ledger notes are public via _render_finding, not private

Any text passed to `record.notes` is published verbatim into a public GitHub issue body. The public-facing path is `src/escape_ledger_loop.py` → `_render_finding` (`:865`) → `create_issue` (`:582`), which predates PR #11197. `docs/arch/generated/escape-ledger.md` and `escape_ledger.jsonl` are both gitignored.

**Why:** Treating notes as internal-only leads to suppression proposals that re-break #11178 (regression-pin path naming in aging close comments).
