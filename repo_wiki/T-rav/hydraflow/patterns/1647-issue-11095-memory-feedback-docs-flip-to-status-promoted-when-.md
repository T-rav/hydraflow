---
id: 1647
topic: patterns
source_issue: 11095
source_phase: plan
created_at: 2026-08-14T08:32:23.164137+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Memory feedback docs flip to status: promoted when enforced in code

When a memory-feedback rule is promoted from a guideline into code enforcement, update the mirror doc's frontmatter: set `status: promoted` and `promoted_in: '#<PR>'` with the implementing PR number.

Example: `docs/wiki/memory-feedback/feedback-subagent-backgrounds-quality-then-stops.md` is flipped from `status: open` to `promoted` once the `SubagentStop` hook ships.

**Why:** Stale `status: open` on an enforced rule causes duplicate work — agents re-discover and re-report an already-solved problem.
