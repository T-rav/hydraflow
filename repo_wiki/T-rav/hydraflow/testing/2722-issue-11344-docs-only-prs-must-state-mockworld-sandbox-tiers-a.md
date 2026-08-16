---
id: 2722
topic: testing
source_issue: 11344
source_phase: plan
created_at: 2026-08-16T13:29:50.590365+00:00
status: active
corroborations: 1
---

# Docs-only PRs must state MockWorld/sandbox tiers as N/A in PR body

Rule: Per `docs/standards/testing/README.md`, even docs-only changes must explicitly state `MockWorld scenario N/A` and `sandbox e2e N/A` in the PR body.

- No phase-crossing or runtime behavior means no test-pyramid tier applies, but the convention requires stating that explicitly.
- Counter-pins in `tests/regressions/` (e.g., still resolves canonical review PR, still drops merged/draft PRs) guard against accidental behavior changes in docs-only PRs.

**Why:** Omitting tier statements triggers review friction on PRs that touch test-adjacent files like fakes or regression tests.
