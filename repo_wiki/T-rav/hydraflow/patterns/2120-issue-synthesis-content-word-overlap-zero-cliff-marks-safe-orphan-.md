---
id: 2120
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.318657+00:00
status: superseded
corroborations: 1
supersedes: 2004
superseded_by: 2236
---

# Content-word overlap zero cliff marks safe orphan restore set

When tiering `left_on_primary` edges for restore, content-word overlap with the fold target has a measurable cliff at zero (0→35 edges, 1→94, 2→108, ≥3→234). Use `--max-overlap` (default 0) to hold blast radius at the cliff; higher tiers are opt-in.

Example: `scripts/repair_wiki_supersession.py --restore-orphans --max-overlap 0` restores only vocabulary-disjoint predecessors.

**Why:** Overlap is a heuristic; defaulting to zero ensures only vocabulary-disjoint predecessors are restored, avoiding false positives where the target legitimately restates the lesson.
