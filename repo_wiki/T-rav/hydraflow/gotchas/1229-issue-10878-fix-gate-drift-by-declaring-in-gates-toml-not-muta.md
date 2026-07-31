---
id: 1229
topic: gotchas
source_issue: 10878
source_phase: plan
created_at: 2026-07-31T07:10:49.839556+00:00
status: active
corroborations: 1
---

# Fix gate drift by declaring in gates.toml, not mutating live GitHub

When a required context exists live but is missing from `gates.toml`, add the `[[gate]]` record and run `make gen-gates` so canonical converges on live with zero GitHub mutation.

- Add `[[gate]]` to `gates.toml` with `name`, `required_on`, `workflow`, `job` fields
- Run `make gen-gates` to regenerate `staging_ruleset.json` and README table
- Verify with `make gen-gates-check` (exits 0 if artifacts match source)

`BranchProtectionAuditorLoop` auto-closes the drift issue on its next clean tick — no manual `--apply` needed.

**Why:** Declaring in contract and regenerating is the forward-fix path; `--apply` is the backward-fix path that de-requires live guardrails.
