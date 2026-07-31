---
id: 1206
topic: gotchas
source_issue: 10823
source_phase: plan
created_at: 2026-07-31T00:48:51.333108+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Attribution ladder: branch prefix > issue refs > loop tag > label > unattributed

Attribute changes to loops using a fixed priority order; never drop a match to `None`.

Ladder: branch prefix → squash-subject issue refs → issue loop tag → label map → `unattributed`.

- `… (#10767 #10762) (#10773)` yields issues `[10767, 10762]`, PR `10773`.
- No match lands in `unattributed`, not silently dropped.
- Report `unattributed` volume so rankings can be discounted.

**Why:** Without a fixed order, attribution is inconsistent and interaction rankings can't be trusted or discounted by confidence.
