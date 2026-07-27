---
id: 1160
topic: gotchas
source_issue: 10726
source_phase: plan
created_at: 2026-07-27T18:34:31.163843+00:00
status: active
corroborations: 1
---

# Low-confidence resolution needs --confidence AND --encoded-as

The `low-confidence` branch of `_resolution_instructions` must print both `--confidence <high|medium>` and `--encoded-as`. Bumping confidence alone satisfies `_surfacing_answered` (`src/escape_ledger_loop.py:200`) but leaves the escape unencoded; `--encoded-as` alone bumps nothing and the surfacing stays open. **Why:** Omitting either flag produces a command that executes successfully but doesn't fully resolve the escape, leaving the surfaced issue stranded.
