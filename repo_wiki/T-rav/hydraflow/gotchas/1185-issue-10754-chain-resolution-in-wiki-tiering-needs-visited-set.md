---
id: 1185
topic: gotchas
source_issue: 10754
source_phase: plan
created_at: 2026-07-27T23:21:47.785770+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Chain resolution in wiki tiering needs visited-set cycle guard

When resolving `left_on_primary` predecessor chains via `plan_topic_repair` output, carry an explicit visited-set to break cycles and classify terminations.

Example: The corpus has multi-hop chains like `gotchas/0841 → 0851 → 1011 → 1039`. A chain ending on a missing id, a cycle, or a non-active entry is counted under suppressed `not_live`, never silently dropped. Predecessors with no repo anchors go to `no_anchor`.

**Why:** Without the guard, a cycle causes infinite recursion; silently dropping suppressed cases hides real coverage gaps from the report.
