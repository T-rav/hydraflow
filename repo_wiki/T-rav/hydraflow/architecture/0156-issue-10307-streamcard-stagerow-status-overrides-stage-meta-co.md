---
id: 0156
topic: architecture
source_issue: 10307
source_phase: plan
created_at: 2026-07-24T04:05:15.039770+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# StreamCard StageRow: status overrides stage meta.color for escalation

In `src/ui/src/components/StreamCard.jsx`, `StageRow`'s `nodeStyle` ternary branches on `status` (e.g. `hitl`, `failed`) before falling back to `meta.color`. This is intentional: `useTimeline` can flag an earlier stage — e.g. `review` (meta color orange) — as `status: 'hitl'` when escalation happens there, so the row must render red regardless of the stage's own meta color. Don't collapse the `hitl` branch into `meta.color` as a "simplification" — it would make escalated non-hitl stages render their stage color instead of the urgent red used by `PIPELINE_STAGES.hitl`, `dotStyles.hitl`, and `badgeStyleMap.hitl`.

**Why:** collapsing the override silently regresses escalated rows (e.g. `review`) to a color that doesn't signal HITL urgency.
