---
id: 0096
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:46:56.518835+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Use `TypedDict(total=False)` for backward-compatible payloads

Define event payload TypedDicts with `total=False` so all fields are optional, allowing old producers and new consumers to interoperate.

Example: `class MergePayload(TypedDict, total=False): pr_number: int; labels: list[str]`.

**Why:** A `total=True` TypedDict requires all fields; adding a new field breaks any existing producer that doesn't include it, preventing rolling deployments.
