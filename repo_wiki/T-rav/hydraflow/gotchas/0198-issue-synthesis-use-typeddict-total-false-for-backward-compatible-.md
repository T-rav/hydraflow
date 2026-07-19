---
id: 0198
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.156658+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Use `TypedDict(total=False)` for backward-compatible payloads

Define event payload TypedDicts with `total=False` so all fields are optional, allowing old producers and new consumers to interoperate.

Example: `class MergePayload(TypedDict, total=False): pr_number: int; labels: list[str]`.

**Why:** A `total=True` TypedDict requires all fields; adding a new field breaks any existing producer that doesn't include it, preventing rolling deployments.
