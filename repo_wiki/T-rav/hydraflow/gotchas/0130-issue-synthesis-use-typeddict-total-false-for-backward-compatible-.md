---
id: 0130
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.468004+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Use `TypedDict(total=False)` for backward-compatible payloads

Define event payload TypedDicts with `total=False` so all fields are optional, allowing old producers and new consumers to interoperate.

Example: `class MergePayload(TypedDict, total=False): pr_number: int; labels: list[str]`.

**Why:** A `total=True` TypedDict requires all fields; adding a new field breaks any existing producer that doesn't include it, preventing rolling deployments.
