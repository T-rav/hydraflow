---
id: 0617
topic: patterns
source_issue: 10622
source_phase: plan
created_at: 2026-07-26T11:28:44.489416+00:00
status: active
corroborations: 1
---

# MIN_SIGNALS minimum is always >=1, never a live count

Set every `MIN_SIGNALS` row `minimum` to `>=1`. Never copy today's live count as the threshold.

- `src/arch/integrity.py` owns the table: `key`, `artifact`, `describes`, `minimum`, optional `waiver`
- Live headroom (subscribers 2, transitions 9, xref edges 375, loops 64, ports 10, fakes 19) is NOT encoded
- A count-based threshold becomes a ratchet every unrelated PR must re-baseline

**Why:** Thresholds copied from current counts force churn on every PR that touches an extractor's input domain, even when the artifact is healthy.
