---
id: 0102
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:31:58.099308+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Extract duplicated JSONL-reading logic to a shared `_load_jsonl()` helper

Shared JSONL-reading logic must be extracted to a `_load_jsonl(path, label)` helper rather than duplicated inline.

Example: `records = _load_jsonl(path, "events")` — one implementation, multiple callers.

**Why:** Inline duplication causes silent divergence when one copy gets a bug fix (e.g., empty-file guard) that the other copies miss.
