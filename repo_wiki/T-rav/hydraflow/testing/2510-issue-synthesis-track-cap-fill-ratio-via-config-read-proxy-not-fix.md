---
id: 2510
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.697152+00:00
status: active
corroborations: 1
supersedes: 2320
---

# Track cap fill ratio via config-read proxy, not fixture assertions

Record every `max_*_chars` config field read during `audit.render_target` by wrapping `_MinimalConfig` in a proxy. Fixtures declare `caps` entries; unmapped reads are tracked and may only shrink.

Example: A fixture with `caps: {"max_plan_chars": 4000}` reports fill ratio = `len(rendered_arg) / 4000`. Unmapped reads are a ratcheted series.

**Why:** Without recording which config caps a render actually consults, fill-ratio floors are unenforceable — fixtures can bypass limits silently.
