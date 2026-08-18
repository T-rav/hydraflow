---
id: 1482
topic: gotchas
source_issue: 11413
source_phase: plan
created_at: 2026-08-18T03:10:14.007917+00:00
status: active
corroborations: 1
---

# Fail-loud exceptions must use LIKELY_BUG_EXCEPTIONS base, not RuntimeError

When a fake's fail-loud exception must escape `reraise_on_credit_or_bug`, base it on a class listed in `exception_classify.LIKELY_BUG_EXCEPTIONS` — a plain `RuntimeError` is absorbed.

- `FakeGitHubUnmodelledCommand(RuntimeError)` → swallowed at `StaleIssueLoop` branch-GC, burying the fidelity gap.
- `FakeGitHubUnmodelledCommand(NotImplementedError)` → re-raised as a likely bug (still a `RuntimeError` subclass, so existing catches hold).

**Why:** The defensive handler treats unclassified `RuntimeError` as a recoverable credit error, silently masking the exact defect the fake is designed to surface.
