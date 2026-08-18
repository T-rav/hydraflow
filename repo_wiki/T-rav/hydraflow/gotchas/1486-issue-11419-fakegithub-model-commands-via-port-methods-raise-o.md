---
id: 1486
topic: gotchas
source_issue: 11419
source_phase: plan
created_at: 2026-08-18T03:36:18.966731+00:00
status: active
corroborations: 1
---

# FakeGitHub: model commands via Port methods, raise on unmodelled shapes

When adding a `gh` command branch to `FakeGitHub._run_gh`, delegate to the existing `PRPort`/fake method (e.g. `update_issue_body`) so fake state has one writer. Unmodelled flag combinations must still raise `FakeGitHubUnmodelledCommand`.

- `issue edit --body X` → `self.update_issue_body(num, body)`
- `issue edit --add-label foo` → raise `FakeGitHubUnmodelledCommand`

**Why:** Returning a blanket `""` for unmodelled shapes (per #11372) silently passes tests that should fail, hiding real writer bugs like the body-clobber in `_verify_issue`.
