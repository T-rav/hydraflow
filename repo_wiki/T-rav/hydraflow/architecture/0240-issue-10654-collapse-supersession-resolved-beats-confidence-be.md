---
id: 0240
topic: architecture
source_issue: 10654
source_phase: plan
created_at: 2026-07-26T16:24:44.376113+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Collapse supersession: resolved beats confidence beats latest

In `latest_by_escape`, when multiple rows share a `detection_ref`, keep exactly one using this priority: resolved (`encoded_as != "none-yet"`) first, then strongest `attribution_confidence` (high>medium>low), then latest appearance.

- This runs *after* `latest_by_id`, so `append_resolution` chains are already collapsed.
- Inverting this order (e.g., latest-wins) would discard a human resolution when a later detector row arrives — the one outcome the append-only design exists to prevent.

**Why:** A later unencoded detector row must never overwrite a human-encoded resolution; the ordering is the invariant that makes read-layer collapse safe.
