---
id: 0194
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.634347+00:00
status: active
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
---

# Use `file_util.atomic_write()` for critical state file updates

Write critical state via `file_util.atomic_write()`, which writes to a temp file then calls `os.replace()` atomically.

Example: `file_util.atomic_write(state_path, json.dumps(state))` — not `open(path, 'w').write(...)`.

**Why:** A crash mid-write with `open(..., 'w')` truncates the file, producing an empty or partial state that cannot be loaded.
