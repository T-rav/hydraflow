---
id: 1721
topic: testing
source_issue: 10860
source_phase: plan
created_at: 2026-07-31T01:48:16.698196+00:00
status: superseded
corroborations: 1
superseded_by: 1814
---

# Track cap fill ratio via config-read proxy, not fixture assertions

Record every `max_*_chars` config field read during `audit.render_target` by wrapping `_MinimalConfig` in a proxy. Fixtures declare `caps` entries; unmapped reads are tracked and may only shrink.

Example: A fixture with `caps: {"max_plan_chars": 4000}` reports fill ratio = `len(rendered_arg) / 4000`. A `max_*_chars` read with no `caps` entry is listed unmapped, and the unmapped count is itself a ratcheted series.

**Why:** Without recording which config caps a render actually consults, fill-ratio floors are unenforceable — fixtures can bypass limits silently.
