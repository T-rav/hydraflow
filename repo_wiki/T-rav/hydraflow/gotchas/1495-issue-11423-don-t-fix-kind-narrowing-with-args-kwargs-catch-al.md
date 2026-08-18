---
id: 1495
topic: gotchas
source_issue: 11423
source_phase: plan
created_at: 2026-08-18T04:02:35.358213+00:00
status: active
corroborations: 1
---

# Don't fix kind-narrowing with *args/**kwargs catch-alls

When a Fake narrows a Port param to keyword-only, remove the `*,` separator — never replace the named param with `**kwargs`.

- A structural pin reads `Parameter.kind` off the named `limit` parameter. If `limit` is absorbed into `**kwargs`, `inspect.signature` reports no named `limit` at all, so the declared contract stays narrowed and the pin still fails.
- The fix in `FakeGitHub.list_closed_issues_by_label` is a one-line `*,` deletion.

**Why:** Catch-alls silence the `TypeError` at runtime but leave the declared signature incompatible, so the conformance sweep and structural pins continue to fail.
