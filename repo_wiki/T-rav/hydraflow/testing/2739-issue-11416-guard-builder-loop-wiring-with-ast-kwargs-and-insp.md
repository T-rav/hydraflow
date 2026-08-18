---
id: 2739
topic: testing
source_issue: 11416
source_phase: plan
created_at: 2026-08-18T03:21:19.601672+00:00
status: stale
corroborations: 1
stale_reason: source issue #11416 closed
---

# Guard builder-loop wiring with AST kwargs and inspect.signature

Rule: Use a runtime guard test (`tests/scenarios/catalog/test_collaborator_wiring.py`) that derives builders from `_BUILDERS`, AST-reads each builder's constructor kwargs, `inspect.signature`s the loop class, and requires every None-guarded optional param to be builder-passed or in an inline allowlist with a reason.

- Allowlist is module-private, self-retiring (fails if a param the loop no longer accepts is listed).
- Failure messages name builder + param + suggested port key.

**Why:** Hardcoded loop lists drift; the AST approach catches new silent omissions as loops add optional collaborators.
