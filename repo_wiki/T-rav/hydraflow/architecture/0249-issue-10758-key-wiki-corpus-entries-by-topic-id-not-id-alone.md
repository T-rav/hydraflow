---
id: 0249
topic: architecture
source_issue: 10758
source_phase: plan
created_at: 2026-07-27T23:48:31.703711+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Key wiki corpus entries by (topic, id), not id alone

Use `(topic, id)` as the composite key everywhere in wiki coverage analysis.

- `gotchas/0001` and `dependencies/0001` are distinct entries that share numeric id `0001`.
- Keying by id alone cross-links them and reports orphans as represented.

**Why:** Numeric ids are only unique within a topic directory; flattening them silently corrupts tiering and triage verdicts.
