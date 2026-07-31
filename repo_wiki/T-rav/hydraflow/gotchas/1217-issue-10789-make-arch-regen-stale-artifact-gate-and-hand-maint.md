---
id: 1217
topic: gotchas
source_issue: 10789
source_phase: plan
created_at: 2026-07-31T02:16:58.506531+00:00
status: active
corroborations: 1
---

# make arch-regen stale-artifact gate and hand-maintained yml input

After editing `docs/arch/functional_areas.yml`, run `make arch-regen` and verify `git diff --exit-code docs/arch/generated/` is clean. Edit the hand-maintained yml, not the generated markdown.

- `docs/arch/functional_areas.yml` is the source input; `docs/arch/generated/*.md` are outputs that will be overwritten on next regen.
- P6 in issue #10789 includes this stale-artifact gate as an acceptance criterion.

**Why:** CI fails if generated output doesn't match the hand-maintained source; editing only the generated docs is silently discarded.
