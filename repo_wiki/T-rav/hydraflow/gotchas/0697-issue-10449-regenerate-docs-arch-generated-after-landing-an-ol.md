---
id: 0697
topic: gotchas
source_issue: 10449
source_phase: plan
created_at: 2026-07-24T12:33:05.988851+00:00
status: superseded
corroborations: 1
superseded_by: 0704
---

# Regenerate docs/arch/generated after landing an old commit, don't reuse its snapshot

When landing a commit that was cut before HEAD advanced (e.g. cherry-picking `cb1d5fd5` onto current `staging`), discard that commit's `docs/arch/generated/` snapshot and re-run `make arch-regen-stage` rather than carrying the stale one forward. **Why:** an old snapshot passes review visually but fails `make arch-check` against the real landed code state — regenerate fresh every time old commits get replayed onto a moved branch.
