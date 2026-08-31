---
id: 2783
topic: testing
source_issue: 11803
source_phase: plan
created_at: 2026-08-30T09:12:38.105436+00:00
status: active
corroborations: 1
---

# Reconcile byte-identical helpers as single unparameterized form

When multiple local copies of a helper are byte-identical (body + docstring), promote the single most general form verbatim — do not parameterize.

Include a reconciliation table in the PR description mapping each local variant (file:line, body, canonical behaviour column stating "identical — subsumed verbatim"). Note out-of-scope copies: `src/wiki_compiler.py:480` `_flow_aborted` (same body, different name), `src/implement_phase/_common.py:95` `_open_pr_terminal` (a composition, not a variant).

**Why:** Parameterizing without callers creates speculative generality and obscures the reconciliation audit trail.
