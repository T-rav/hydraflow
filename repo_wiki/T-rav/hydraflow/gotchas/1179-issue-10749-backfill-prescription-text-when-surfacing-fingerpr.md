---
id: 1179
topic: gotchas
source_issue: 10749
source_phase: plan
created_at: 2026-07-27T22:53:04.998256+00:00
status: active
corroborations: 1
---

# Backfill prescription text when surfacing fingerprints are spent

When fixing `_render_finding` body text in `src/escape_ledger_loop.py`, also run a one-shot backfill posting correction comments to already-filed open issues.

- `scripts/backfill_escape_surfacing_prescription.py`: `--dry-run` default, idempotent, posts via `PRPort`, scans the surfaces ledger at runtime rather than hardcoding issue numbers.
- Un-spending fingerprints was rejected — it would file duplicates alongside the originals.

**Why:** Surfacing fingerprints are one-shot budgets; spent fingerprints can never re-file with corrected text, leaving issues permanently orphaned.
