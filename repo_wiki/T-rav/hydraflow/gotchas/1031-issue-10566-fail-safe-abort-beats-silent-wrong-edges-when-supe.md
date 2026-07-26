---
id: 1031
topic: gotchas
source_issue: 10566
source_phase: plan
created_at: 2026-07-25T23:57:01.883157+00:00
status: active
corroborations: 1
---

# Fail-safe abort beats silent wrong-edges when supersession is ambiguous

When `wiki_compiler.py`'s resolved-mapping logic can't match every input to a declared or title-matched output, the correct behavior is to write nothing and leave inputs `status: active` — the same fail-safe shape the anchor gate already uses elsewhere in the compiler. Log the topic and the unmatched ids with a literal format string (per `docs/wiki/gotchas.md`) rather than silently picking a default target.

**Why:** a silent fallback (e.g. "just point at the first output") is exactly the bug being fixed — it's tempting to reuse and it reproduces the cartesian-graph escape.
