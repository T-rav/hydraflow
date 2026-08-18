---
id: 1499
topic: gotchas
source_issue: 11423
source_phase: review
created_at: 2026-08-18T05:56:04.201989+00:00
status: active
corroborations: 1
---

# _signatures_compatible is kind-blind — positional calls bypass checks

`_signatures_compatible` in the live code does not distinguish positional from keyword arguments.

A caller passing `limit` positionally bypasses checks that a keyword-passing caller would fail. This hole (from #11415) survives deliberately and must be documented via a context test against the live function.

**Why:** Kind-blindness means the signature gate provides false assurance for positional call sites — tests must exercise the live `_signatures_compatible`, not a local copy.
