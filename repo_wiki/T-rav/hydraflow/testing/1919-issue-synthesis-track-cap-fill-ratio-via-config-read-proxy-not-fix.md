---
id: 1919
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:06.505865+00:00
status: superseded
corroborations: 1
supersedes: 1814
superseded_by: 2046
---

# Track cap fill ratio via config-read proxy, not fixture assertions

Record every `max_*_chars` config field read during `audit.render_target` by wrapping `_MinimalConfig` in a proxy. Fixtures declare `caps` entries; unmapped reads are tracked and may only shrink.

Example: A fixture with `caps: {"max_plan_chars": 4000}` reports fill ratio = `len(rendered_arg) / 4000`. A `max_*_chars` read with no `caps` entry is listed unmapped, and the unmapped count is itself a ratcheted series.

**Why:** Without recording which config caps a render actually consults, fill-ratio floors are unenforceable — fixtures can bypass limits silently.
