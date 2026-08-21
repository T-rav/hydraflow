---
id: 1508
topic: gotchas
source_issue: 11457
source_phase: plan
created_at: 2026-08-18T12:04:53.781907+00:00
status: active
corroborations: 1
---

# Fail-open on GitHub state reads inside ImplementPhase gates

Rule: wrap `PRPort.get_issue_state` reads in try/except and return a safe default (not-resolved) on any exception, re-raising only on credit/bug signals.

Example: `_issue_resolved_elsewhere` in `src/implement_phase.py` catches `Exception`, calls `reraise_on_credit_or_bug(exc)`, then returns `False`. Treating `UNKNOWN`/`""` as closed would silently halt the factory — they are `PRManager.get_issue_state`'s error returns.

**Why:** A GitHub hiccup must never block a build; fail-open is load-bearing for the dark-factory.
