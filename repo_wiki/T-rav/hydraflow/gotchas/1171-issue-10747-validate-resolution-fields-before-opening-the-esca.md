---
id: 1171
topic: gotchas
source_issue: 10747
source_phase: plan
created_at: 2026-07-27T22:30:25.835010+00:00
status: stale
corroborations: 1
stale_reason: source issue #10747 closed
---

# Validate resolution fields before opening the escape ledger

Place the "at least one of encoded_as / attribution_confidence" guard in `resolve_escape` (`src/escape/resolve.py`) before the ledger is touched. An all-`None` call would append a no-op superseding row that answers nothing and silently pre-answers the wrong surface.

- `resolve_escape` raises `EscapeResolveError` for empty resolutions.
- `encoded_as="none-yet"` is still rejected via `InvalidEncodingError`.

**Why:** Appending first and validating second leaves a no-op row in the JSONL that the loop treats as resolved.
