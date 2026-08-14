---
id: 1266
topic: gotchas
source_issue: 11090
source_phase: plan
created_at: 2026-08-14T06:25:31.261915+00:00
status: active
corroborations: 1
---

# Promote memory-feedback by flipping frontmatter status

To retire a feedback mirror, set `status: promoted` and `promoted_in: '#<PR>'` in the file under `docs/wiki/memory-feedback/`. Also add a `docs/wiki/gotchas.md` entry (prose + `json:entry`) capturing the promoted rule.

**Why:** `MemoryBacklogLoop` re-files any mirror whose frontmatter lacks `promoted_in`; the flip is the only durable stop signal.
