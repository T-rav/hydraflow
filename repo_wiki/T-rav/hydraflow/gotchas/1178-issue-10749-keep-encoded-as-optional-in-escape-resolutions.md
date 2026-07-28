---
id: 1178
topic: gotchas
source_issue: 10749
source_phase: plan
created_at: 2026-07-27T22:53:04.998247+00:00
status: active
corroborations: 1
---

# Keep encoded_as optional in escape resolutions

Make `encoded_as` optional so confidence-only resolutions don't force fabricated encodings.

- `src/escape/ledger.py:append_resolution`: override only when not None (mirrors `attribution_confidence`).
- `src/escape/resolve.py:resolve_escape`: keep positional slot, default `None`; raise `EscapeResolveError` subclass when neither field given.
- `scripts/resolve_escape.py`: `--encoded-as required=False`, exit 2 with clear message when neither flag present.

**Why:** Fabricating an encoding writes false data into a falsification instrument and pre-empts the row's later `aging` surface.
