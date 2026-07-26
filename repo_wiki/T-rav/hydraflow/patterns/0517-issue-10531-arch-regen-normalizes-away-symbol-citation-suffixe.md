---
id: 0517
topic: patterns
source_issue: 10531
source_phase: plan
created_at: 2026-07-25T09:52:15.451026+00:00
status: superseded
corroborations: 1
superseded_by: 0523
---

# arch-regen normalizes away :Symbol citation suffixes — expect a no-op diff

`adr_xref` (run via `make arch-regen`) strips `:Symbol` suffixes when generating downstream artifacts, so narrowing an ADR citation from bare `src/foo.py` to `` `src/foo.py:Symbol` `` should produce zero diff in `docs/arch/generated/`. When verifying an ADR-citation-only change (e.g. ADR-0108's B5 row), run `make arch-regen` and confirm `git diff --stat` shows only the ADR file changed and no `src/` files — that's the acceptance signal that the fix stayed doc-only. **Why:** if `arch-regen` produces unexpected generated-artifact diffs after a citation edit, the `:Symbol` syntax likely broke the xref parser rather than being cleanly normalized.
