---
id: 0285
topic: architecture
source_issue: 10867
source_phase: review
created_at: 2026-07-31T10:45:43.194347+00:00
status: active
corroborations: 1
---

# make arch-regen must reproduce committed docs byte-for-byte

After any change to architecture docs or ADR enforcement state, run `make arch-regen` and verify the output matches committed files exactly. The only acceptable diff is `changelog.md`'s self-referential commit-hash lag.

Any other diff means a generated doc was hand-edited or a regen step was skipped.

**Why:** Drift between committed and regenerated docs breaks `test_arch_freshness` and `test_arch_integrity`.
