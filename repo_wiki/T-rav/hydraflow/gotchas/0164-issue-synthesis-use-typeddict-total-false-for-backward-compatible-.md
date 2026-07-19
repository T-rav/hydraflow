---
id: 0164
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.952918+00:00
status: active
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
---

# Use `TypedDict(total=False)` for backward-compatible payloads

Define event payload TypedDicts with `total=False` so all fields are optional, allowing old producers and new consumers to interoperate.

Example: `class MergePayload(TypedDict, total=False): pr_number: int; labels: list[str]`.

**Why:** A `total=True` TypedDict requires all fields; adding a new field breaks any existing producer that doesn't include it, preventing rolling deployments.
