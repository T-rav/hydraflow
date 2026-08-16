---
id: 2655
topic: testing
source_issue: 11277
source_phase: plan
created_at: 2026-08-15T21:08:01.026775+00:00
status: active
corroborations: 1
---

# toRailsHealth is the single view-model seam for Rails health

All mapping from backend `Finding` objects to UI violation rows flows through `toRailsHealth` in `src/ui/src/operator/model/railsHealth.js`. Thread new fields (e.g. `finding.fixable`) through this function only, never bypass it in the panel. Defensive-default missing fields to `false` so older payloads don't break the UI.
**Why:** A single mapping point keeps `RepoHealthPanel.jsx` free of backend-shape assumptions and makes vitest coverage tractable.
