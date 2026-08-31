---
id: 4082
topic: patterns
source_issue: 11544
source_phase: plan
created_at: 2026-08-30T15:37:21.169344+00:00
status: active
corroborations: 1
---

# Thread Fable driver lineage across all gateway surfaces at once

When adding Fable driver/child lineage (driver id, parent/child spawn ids, depth), update all four gateway surfaces in a single phase: `route_mint.py`, `active_routes.py`, `ledger.py`, and `models.py`.

Example: Add lineage as optional fields on existing models so v1 (unbound) rows parse as null rather than fabricating data.

**Why:** Half-threading lineage produces receipts that look complete but yields cost rollups that cannot attribute a child spawn.
