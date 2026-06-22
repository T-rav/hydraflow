---
id: 0028
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.695927+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Use `TypedDict(total=False)` for backward-compatible event payloads

Define event payload TypedDicts with `total=False` so all fields are optional, allowing old producers and new consumers to interoperate.

Example: `class MergePayload(TypedDict, total=False): pr_number: int; labels: list[str]`.

**Why:** A `total=True` TypedDict requires all fields; adding a new field breaks any existing producer that doesn't include it, preventing rolling deployments.
