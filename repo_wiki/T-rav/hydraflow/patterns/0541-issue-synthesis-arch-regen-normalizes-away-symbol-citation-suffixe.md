---
id: 0541
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:44:03.245999+00:00
status: stale
corroborations: 1
supersedes: 0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522
stale_reason: drift_detected: src/foo.py
---

# arch-regen normalizes away :Symbol citation suffixes — expect a no-op diff

`adr_xref` (run via `make arch-regen`) strips `:Symbol` suffixes when generating downstream artifacts, so narrowing an ADR citation from bare `src/foo.py` to `` `src/foo.py:Symbol` `` should produce zero diff in `docs/arch/generated/`. When verifying an ADR-citation-only change (e.g. ADR-0108's B5 row), run `make arch-regen` and confirm `git diff --stat` shows only the ADR file changed and no `src/` files — that's the acceptance signal that the fix stayed doc-only. See also: patterns — ADR citations must be symbol-qualified or they drift-flag every file touch.

**Why:** if `arch-regen` produces unexpected generated-artifact diffs after a citation edit, the `:Symbol` syntax likely broke the xref parser rather than being cleanly normalized.
