---
id: 2599
topic: testing
source_issue: 11163
source_phase: plan
created_at: 2026-08-14T18:57:58.285615+00:00
status: stale
corroborations: 1
stale_reason: source issue #11163 closed
---

# "Terminal" in escape ledger means a parsed verdict, not row presence

`terminal_ids()` returns only ids whose latest sidecar row parses to `RESOLVED_ENCODED` or `DISMISSED`. Unreadable rows, rows missing the `diagnosis` key, and `inconclusive` rows are explicitly NOT terminal — last row wins, so a dismissal followed by an unreadable row is no longer terminal.

This unblocks the documented re-diagnose recovery: the escape reaches `diagnose()`, `verdict_for()` returns `None`, and the pass appends a fresh parseable row in the same tick — self-healing, no data repair.

**Why:** Gating `_surface_findings` (`escape_ledger_loop.py:218`) on row presence drops unparseable escapes from every human surface forever.
