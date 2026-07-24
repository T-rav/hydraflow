---
id: 0202
topic: architecture
source_issue: 10486
source_phase: review
created_at: 2026-07-24T22:14:13.479991+00:00
status: active
corroborations: 1
---

# Sibling alert `runs_gc_loop.py` caps join lists (`breaks[:5]`); unpushed_branch_alert doesn't

`runs_gc_loop.py:143-152`'s `audit_chain_break` alert truncates its joined list to `breaks[:5]` before building `message`, but `src/unpushed_branch_alert.py:95-99` embeds the full unbounded `detail` join with no cap. A checkout with many stale local branches can produce an overlong single-line banner. Not blocking to merge (mirrors the issue's literal wording and the pre-existing log line), but a good pattern to copy if this alert's join list grows unbounded in practice.

**Why:** Unbounded joins in user-facing `SYSTEM_ALERT` `message` fields can produce unreadable banners; `runs_gc_loop.py` already solved this for a sibling alert.
